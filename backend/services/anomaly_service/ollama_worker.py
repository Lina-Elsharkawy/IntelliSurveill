from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import ollama
import psycopg
from pgvector.psycopg import register_vector
from PIL import Image

from config import DB_DSN, OLLAMA_HOST, VLM_MODEL, LLM_MODEL
from evidence_io import fetch_clip_frames, fetch_image_rgb, fetch_jpeg_bytes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reasoning_worker")

# Ollama timeouts and retry config
OLLAMA_TIMEOUT_SEC = 120
OLLAMA_MAX_RETRIES = 3


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _client() -> ollama.Client:
    """Create an Ollama client.

    Some older ollama Python clients do not accept timeout=. Keep the worker
    bootable in both environments, while still using the timeout when supported.
    """
    try:
        return ollama.Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SEC)
    except TypeError:
        log.warning("Installed ollama client does not support timeout=; continuing without client timeout")
        return ollama.Client(host=OLLAMA_HOST)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {"raw": value}
    return dict(value)


def image_array_to_jpeg_bytes(frame) -> bytes:
    img = Image.fromarray(frame).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def make_temporal_strip(frames_bytes: list[bytes], max_frames: int = 4) -> bytes:
    """
    Concatenate up to max_frames person-crop JPEGs side-by-side into a single
    horizontal strip so the VLM sees the motion sequence as one image.
    """
    imgs = []
    for b in frames_bytes[:max_frames]:
        try:
            imgs.append(Image.open(io.BytesIO(b)).convert("RGB"))
        except Exception:
            continue
    if not imgs:
        return b""
    max_h = max(img.height for img in imgs)
    # Resize each frame to the same height preserving aspect ratio
    resized = []
    for img in imgs:
        scale = max_h / img.height
        resized.append(img.resize((int(img.width * scale), max_h), Image.LANCZOS))
    strip = Image.new("RGB", (sum(r.width for r in resized), max_h))
    x = 0
    for r in resized:
        strip.paste(r, (x, 0))
        x += r.width
    buf = io.BytesIO()
    strip.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def select_representative_frames(
    frames_or_refs: list[Any],
    max_frames: int = 4,
    prefer_middle: bool = False
) -> list[Any]:
    """
    Select representative frames from beginning, middle, and end rather than just the first N.
    
    Args:
        frames_or_refs: List of frame data or references
        max_frames: Maximum number of frames to return
        prefer_middle: If True, bias selection toward middle frames (useful for peak anomaly)
    """
    if not frames_or_refs or max_frames <= 0:
        return []
    
    n = len(frames_or_refs)
    if n <= max_frames:
        return frames_or_refs
    
    if max_frames == 1:
        # Return middle frame for single frame selection
        return [frames_or_refs[n // 2]]
    
    if prefer_middle and max_frames >= 3:
        # For anomaly peaks, bias toward middle: [start, mid-1, mid, mid+1, end]
        indices = []
        indices.append(0)  # Start
        mid = n // 2
        for offset in range(-(max_frames - 2) // 2, (max_frames - 2) // 2 + 1):
            idx = mid + offset
            if 0 < idx < n - 1:
                indices.append(idx)
        indices.append(n - 1)  # End
        indices = sorted(set(indices))[:max_frames]
    else:
        # Evenly distributed: beginning, middle, end
        indices = [int(i * (n - 1) / (max_frames - 1)) for i in range(max_frames)]
    
    return [frames_or_refs[i] for i in indices]


def resolve_candidate_images(request_json: dict[str, Any]) -> tuple[list[bytes], list[bytes]]:
    """
    Resolve visual evidence for the VLM step with improved frame selection.

    Returns (person_frames_bytes, context_frames_bytes) separately so the caller
    can compose a temporal strip from person crops and pass context as ancillary.

    Priority order for person frames:
      1. person_frames refs  (individual crop JPEGs — most informative for score)
      2. person_clip_ref     (sampled from clip as fallback)

    Priority order for context frames:
      1. representative_frame_ref  (single key frame anchor)
      2. context_frames refs
      3. context_clip_ref
      
    Uses improved frame selection to get beginning, middle, and end frames.
    """
    MAX_PERSON = 4
    MAX_CONTEXT = 3  # Increased from 2 for better multi-person detection

    # ── Person crop frames ──
    person_refs: list[str] = []
    for ref in (request_json.get("person_frames") or []):
        person_refs.append(ref)
    
    # Select representative frames from person_frames
    selected_person_refs = select_representative_frames(person_refs, MAX_PERSON, prefer_middle=True)
    
    person_bytes: list[bytes] = []
    for ref in selected_person_refs:
        try:
            b = fetch_jpeg_bytes(ref)
            if b:
                person_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch person frame %s: %s", ref, e)

    if len(person_bytes) < MAX_PERSON and request_json.get("person_clip_ref"):
        try:
            frames = fetch_clip_frames(request_json["person_clip_ref"], n=MAX_PERSON - len(person_bytes))
            person_bytes.extend(image_array_to_jpeg_bytes(f) for f in frames[: MAX_PERSON - len(person_bytes)])
        except Exception as e:
            log.warning("Could not fetch person clip %s: %s", request_json.get("person_clip_ref"), e)

    # ── Context / scene frames ──
    context_bytes: list[bytes] = []
    if request_json.get("representative_frame_ref"):
        try:
            b = fetch_jpeg_bytes(request_json["representative_frame_ref"])
            if b:
                context_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch representative frame: %s", e)

    context_refs: list[str] = []
    for ref in (request_json.get("context_frames") or []):
        context_refs.append(ref)
    
    # Select representative context frames
    selected_context_refs = select_representative_frames(context_refs, MAX_CONTEXT - len(context_bytes))
    
    for ref in selected_context_refs:
        try:
            b = fetch_jpeg_bytes(ref)
            if b:
                context_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch context frame %s: %s", ref, e)

    if len(context_bytes) < MAX_CONTEXT and request_json.get("context_clip_ref"):
        try:
            frames = fetch_clip_frames(request_json["context_clip_ref"], n=MAX_CONTEXT - len(context_bytes))
            context_bytes.extend(image_array_to_jpeg_bytes(f) for f in frames[: MAX_CONTEXT - len(context_bytes)])
        except Exception as e:
            log.warning("Could not fetch context clip %s: %s", request_json.get("context_clip_ref"), e)

    return person_bytes, context_bytes


def compose_vlm_images(person_bytes: list[bytes], context_bytes: list[bytes]) -> list[bytes]:
    """
    Build the final image list sent to the VLM:
    - A single temporal strip of person crop frames (shows motion arc)
    - Followed by individual context/scene frames
    """
    result: list[bytes] = []
    if person_bytes:
        strip = make_temporal_strip(person_bytes, max_frames=4)
        if strip:
            result.append(strip)
    result.extend(context_bytes)
    return result[:6]  # hard cap — most VLMs handle ≤6 images reliably


def ollama_generate(client: ollama.Client, *, model: str, prompt: str, images: list[bytes] | None = None, retry: int = 0) -> str:
    """
    Call Ollama generate with retry logic and timeout handling.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "repeat_penalty": 1.1, "num_predict": 512, "num_ctx": 4096},
    }
    if images:
        kwargs["images"] = images
    
    for attempt in range(retry + 1):
        try:
            resp = client.generate(**kwargs)
            return (resp.get("response") or "").strip()
        except Exception as e:
            if attempt == retry:
                log.error("Ollama generate failed after %d attempts: %s", retry + 1, e)
                raise
            log.warning("Ollama generate attempt %d failed: %s, retrying...", attempt + 1, e)
            time.sleep(2 ** attempt)  # Exponential backoff
    return ""


def ollama_chat(client: ollama.Client, *, model: str, prompt: str, retry: int = 0) -> str:
    """
    Call Ollama chat with retry logic and timeout handling.
    """
    for attempt in range(retry + 1):
        try:
            resp = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.0, "num_ctx": 8192},
            )
            return ((resp.get("message") or {}).get("content") or "").strip()
        except Exception as e:
            if attempt == retry:
                log.error("Ollama chat failed after %d attempts: %s", retry + 1, e)
                raise
            log.warning("Ollama chat attempt %d failed: %s, retrying...", attempt + 1, e)
            time.sleep(2 ** attempt)
    return ""


def parse_final_decision(text: str) -> dict[str, str | None]:
    """Legacy parser for backwards compatibility - kept as fallback only"""
    text = text or ""
    alert = re.search(r"ALERT\s*:\s*(YES|NO)", text, flags=re.IGNORECASE)
    severity = re.search(r"SEVERITY\s*:\s*(LOW|MEDIUM|HIGH)", text, flags=re.IGNORECASE)
    reason = re.search(r"REASON\s*:\s*(.+)", text, flags=re.IGNORECASE)
    return {
        "alert_decision": alert.group(1).upper() if alert else None,
        "severity": severity.group(1).upper() if severity else None,
        "decision_reason": reason.group(1).strip() if reason else None,
    }


def strip_model_reasoning(text: str) -> str:
    """Remove model thinking tags and surrounding noise while preserving useful answer text."""
    text = text or ""
    # If the model emitted a closed thinking block, remove it completely.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # If it emitted standalone or unclosed tags, remove only the tags so we do not lose the answer.
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return text.strip()


def extract_json_object(text: str) -> str:
    """Extract the first JSON object from a response that may contain prose/code fences."""
    text = strip_model_reasoning(text)
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()
    return text.strip()


def _coerce_rule_id_list(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except Exception:
            continue
    return result


def _allowed_rule_ids(rules: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for r in rules or []:
        try:
            ids.add(int(r.get("id")))
        except Exception:
            continue
    return ids


def parse_structured_decision(
    response_text: str,
    matched_trigger_rules: list[dict[str, Any]] | None = None,
    matched_suppress_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Parse, repair, and validate the strict JSON decision returned by the final LLM.

    Safety rules:
    - Do not silently convert malformed decisions to ALERT=NO.
    - Remove model <think> text and extract the JSON object if extra prose appears.
    - If the model puts matched rule IDs inside `uncertainty`, repair that shape.
    - Never accept invented rule IDs; keep only IDs that were actually pre-matched by the backend.
    """
    text = extract_json_object(response_text or "")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return {"parse_error": f"Invalid JSON: {e}", "raw": text}

    if not isinstance(parsed, dict):
        return {"parse_error": "Decision JSON must be an object", "raw": text}

    # Repair common bad model output:
    # "uncertainty": {"matched_trigger_rules": [...], "matched_suppress_rules": [...]}
    uncertainty_value = parsed.get("uncertainty")
    if isinstance(uncertainty_value, dict):
        if "matched_trigger_rules" not in parsed and "matched_trigger_rules" in uncertainty_value:
            parsed["matched_trigger_rules"] = uncertainty_value.get("matched_trigger_rules")
        if "matched_suppress_rules" not in parsed and "matched_suppress_rules" in uncertainty_value:
            parsed["matched_suppress_rules"] = uncertainty_value.get("matched_suppress_rules")
        # Keep a readable uncertainty string only if the model provided one.
        parsed["uncertainty"] = uncertainty_value.get("uncertainty") or uncertainty_value.get("note") or None

    required = ["alert_decision", "severity", "event_type", "confidence", "reason"]
    missing = [f for f in required if f not in parsed]
    if missing:
        return {"parse_error": f"Missing fields: {missing}", "raw": text}

    parsed["alert_decision"] = str(parsed.get("alert_decision", "")).upper().strip()
    parsed["severity"] = str(parsed.get("severity", "")).upper().strip()
    parsed["event_type"] = str(parsed.get("event_type", "other")).strip()

    allowed_events = {
        "intrusion", "loitering", "after_hours", "fall_detected", "fight_detection",
        "camera_tamper", "sudden_movement", "smoke_fire", "crowd_detection", "other"
    }
    if parsed["alert_decision"] not in {"YES", "NO"}:
        return {"parse_error": f"Invalid alert_decision: {parsed['alert_decision']}", "raw": text}
    if parsed["severity"] not in {"LOW", "MEDIUM", "HIGH"}:
        return {"parse_error": f"Invalid severity: {parsed['severity']}", "raw": text}
    if parsed["event_type"] not in allowed_events:
        parsed["event_type"] = "other"

    try:
        conf = float(parsed.get("confidence"))
        parsed["confidence"] = max(0.0, min(1.0, conf))
    except Exception:
        return {"parse_error": "confidence must be numeric", "raw": text}

    parsed["reason"] = str(parsed.get("reason") or "").strip()
    if not parsed["reason"]:
        return {"parse_error": "reason cannot be empty", "raw": text}

    valid_trigger_ids = _allowed_rule_ids(matched_trigger_rules or [])
    valid_suppress_ids = _allowed_rule_ids(matched_suppress_rules or [])

    parsed["matched_trigger_rules"] = [
        rid for rid in _coerce_rule_id_list(parsed.get("matched_trigger_rules"))
        if rid in valid_trigger_ids
    ]
    parsed["matched_suppress_rules"] = [
        rid for rid in _coerce_rule_id_list(parsed.get("matched_suppress_rules"))
        if rid in valid_suppress_ids
    ]

    parsed["visual_evidence"] = str(parsed.get("visual_evidence") or "").strip()
    parsed.setdefault("uncertainty", None)
    if parsed["uncertainty"] not in (None, ""):
        parsed["uncertainty"] = str(parsed["uncertainty"]).strip()
    else:
        parsed["uncertainty"] = None

    return parsed


def _contains_any(text: str, terms: list[str]) -> bool:
    text_l = (text or "").lower()
    return any(term in text_l for term in terms)


def _has_negated_evidence(narrative: str, concepts: list[str]) -> bool:
    """Detect common VLM phrases that explicitly deny an event/condition."""
    n = (narrative or "").lower()
    negators = [
        "no", "not", "without", "lacks", "lack of", "no clear", "no evidence of",
        "not evident", "not visible", "none", "does not", "do not",
    ]
    for concept in concepts:
        c = concept.lower()
        patterns = [
            f"no {c}", f"no clear {c}", f"no evidence of {c}", f"without {c}",
            f"lacks {c}", f"lack of {c}", f"{c} is not evident", f"{c} not evident",
            f"{c} is not visible", f"{c} not visible",
        ]
        if any(p in n for p in patterns):
            return True
    # Windowed fallback: negator appears shortly before the concept.
    tokens = re.findall(r"[a-z0-9_'-]+", n)
    for i, tok in enumerate(tokens):
        if any(tok == neg or tok.startswith(neg) for neg in ["no", "without", "lacks"]):
            window = " ".join(tokens[i:i + 8])
            if any(concept.lower() in window for concept in concepts):
                return True
    return False


def _has_multi_person_evidence(narrative: str) -> bool:
    n = (narrative or "").lower()
    if _contains_any(n, [
        "only one person", "single person", "one person is visible", "only one individual",
        "no other individuals", "no additional people", "no other persons", "no other people",
        "no additional individuals", "no other person", "one person consistently",
    ]):
        return False
    return _contains_any(n, [
        "two people", "two persons", "two individuals", "two figures", "second person",
        "another person", "another figure", "other person", "other individual", "multiple people",
        "multiple persons", "group", "crowd", "people are", "individuals are",
    ])


def _has_physical_contact_evidence(narrative: str) -> bool:
    n = (narrative or "").lower()
    concepts = ["physical contact", "physical interaction", "pushing", "grabbing", "hitting", "confrontation", "altercation"]
    if _has_negated_evidence(n, concepts):
        return False
    return _contains_any(n, [
        "physical contact", "physical interaction", "touching", "close physical contact",
        "push", "pushing", "grab", "grabbing", "hit", "hitting", "kick", "kicking",
        "pulling", "blocking", "chasing", "lunging", "striking", "restraining",
        "defensive posture", "aggressive posture", "aggressive interaction", "hostile movement",
        "confrontation", "altercation", "fight", "fighting",
    ])


def _has_fight_evidence(narrative: str) -> bool:
    """Require multi-person + contact/aggression, unless the narrative explicitly says fighting."""
    n = (narrative or "").lower()
    if _has_negated_evidence(n, [
        "physical contact", "physical interaction", "confrontation", "aggressive", "fight", "fighting",
        "additional people", "other individuals", "other persons",
    ]):
        return False
    explicit_fight = _contains_any(n, ["fight", "fighting", "altercation", "brawl", "violence"])
    return (explicit_fight and _has_physical_contact_evidence(n)) or (_has_multi_person_evidence(n) and _has_physical_contact_evidence(n))


def _has_fall_evidence(narrative: str) -> bool:
    n = (narrative or "").lower()
    if _has_negated_evidence(n, ["fall", "falling", "collapse", "stumble", "unable to stand", "lying on the floor"]):
        return False
    return _contains_any(n, [
        "falls", "falling", "fell", "collapsed", "collapse", "on the ground", "on the floor",
        "lying on the floor", "lying on the ground", "unable to stand", "cannot stand",
        "appears unable to stand", "stumbles severely", "severe stumble", "tripped and fell",
    ])


def _has_sudden_movement_evidence(narrative: str) -> bool:
    n = (narrative or "").lower()
    if _contains_any(n, [
        "motion appears completely normal", "smooth/continuous", "steady pace", "normal walking",
        "routine movement", "no abrupt", "no running", "no rapid movement",
    ]):
        return False
    return _contains_any(n, [
        "running", "sprinting", "rapid movement", "sudden movement", "abrupt movement",
        "erratic movement", "abrupt turns", "unstable tracking", "lost_frames", "track instability",
        "multiple stops", "hesitant", "irregular gait", "unusual lateral",
    ])


def _has_normal_activity_evidence(narrative: str) -> bool:
    n = (narrative or "").lower()
    if _contains_any(n, [
        "erratic", "abrupt", "unstable", "lost_frames", "track instability", "fall", "falling",
        "collapse", "physical contact", "confrontation", "aggressive", "interaction", "leaning",
        "hesitant", "irregular", "unusual", "unable to stand", "stumble",
    ]):
        return False
    return _contains_any(n, [
        "normal walking", "walking normally", "standing normally", "steady pace", "smooth/continuous",
        "completely normal", "routine", "upright posture", "no physical contact", "no confrontation",
        "no aggressive", "no suspicious",
    ])


def _infer_events_from_text(narrative: str) -> set[str]:
    """Infer coarse event types from the VLM narrative for rule pre-matching.

    This is intentionally conservative. Earlier versions matched fight/fall rules
    from words like "contact", "leaning", or "dynamic" even when the VLM said
    there was only one person and no confrontation. That polluted the final LLM
    prompt with irrelevant rules. Here, each event requires positive evidence and
    respects explicit negative statements from the VLM.
    """
    n = (narrative or "").lower()
    events: set[str] = set()
    if _has_fight_evidence(n):
        events.add("fight_detection")
    if _has_sudden_movement_evidence(n):
        events.add("sudden_movement")
    if _has_fall_evidence(n):
        events.add("fall_detected")
    if _contains_any(n, ["crowd", "large group", "many people", "gathering"]):
        events.add("crowd_detection")
    if _contains_any(n, ["smoke", "fire", "flame", "burning"]):
        events.add("smoke_fire")
    if _contains_any(n, ["camera blocked", "camera covered", "camera obstructed", "tamper"]):
        events.add("camera_tamper")
    if _contains_any(n, ["loiter", "loitering", "standing still", "waiting for a long time"]):
        events.add("loitering")
    return events


def _parse_event_hour(window_start_ts: Any) -> int | None:
    """Use the candidate event time, not worker processing time, for time-based rules."""
    if not window_start_ts:
        return None
    try:
        ts = str(window_start_ts).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(ts).hour
    except Exception:
        return None


def _condition_words_match(narrative: str, value: Any) -> bool:
    """Keyword check for simple condition phrases.

    Uses all meaningful words rather than "any word" for target behaviors. This
    avoids matching "appears unable to stand" just because the narrative contains
    the word "appears" or "stand".
    """
    if value in (None, "", "All"):
        return True
    n = (narrative or "").lower()
    words = [w.strip(" .,;:!?()[]{}\"'").lower() for w in str(value).split()]
    stop = {
        "person", "someone", "anyone", "with", "the", "and", "involved", "appears",
        "appear", "visible", "normal", "normally", "behavior", "activity", "target",
    }
    words = [w for w in words if len(w) > 2 and w not in stop]
    if not words:
        return True
    # Color/descriptors: one content word is enough. Behaviors: all content words must be present.
    if len(words) == 1:
        return words[0] in n
    return all(w in n for w in words)


def _rule_requires_color(rule: dict[str, Any], conditions: dict[str, Any]) -> str | None:
    text = _rule_text_and_conditions(rule, conditions)
    for color in ["pink", "red", "blue", "green", "yellow", "black", "white", "gray", "grey", "brown"]:
        if color in text:
            return color
    return None


def _is_normal_suppress_rule(rule: dict[str, Any], conditions: dict[str, Any]) -> bool:
    text = _rule_text_and_conditions(rule, conditions)
    return str(rule.get("rule_type") or "").lower() == "suppress" and _contains_any(
        text,
        ["standing normally", "walking normally", "normal standing", "normal walking", "simply walking", "routine movement"],
    )


def _visual_conditions_match(rule: dict[str, Any], conditions: dict[str, Any], event_type: str, narrative: str) -> tuple[bool, list[str]]:
    """Check visually observable rule conditions against the VLM narrative.

    The checks are stricter for fight/fall/color/normal-suppress rules so the
    final LLM only sees rules that are genuinely relevant.
    """
    reasons: list[str] = []
    rule_text = _rule_text_and_conditions(rule, conditions)

    required_color = (conditions.get("shirt_color") or conditions.get("clothing_color") or _rule_requires_color(rule, conditions))
    if required_color:
        if not _condition_words_match(narrative, required_color):
            return False, [f"required color '{required_color}' not visible in narrative"]
        reasons.append(f"required_color={required_color}")

    if _is_normal_suppress_rule(rule, conditions):
        if not _has_normal_activity_evidence(narrative):
            return False, ["normal suppress rule not supported by narrative"]
        reasons.append("normal_activity_supported=true")

    if event_type == "fight_detection" or "physical interaction" in rule_text or "physical contact" in rule_text or "aggressive" in rule_text:
        if not _has_fight_evidence(narrative):
            return False, ["fight/physical-interaction evidence not supported by narrative"]
        reasons.append("fight_evidence=true")

    if event_type == "fall_detected" or "unable to stand" in rule_text or "falls" in rule_text or "collapses" in rule_text:
        if not _has_fall_evidence(narrative):
            return False, ["fall/collapse evidence not supported by narrative"]
        reasons.append("fall_evidence=true")

    if event_type == "sudden_movement" and not _has_sudden_movement_evidence(narrative):
        return False, ["sudden movement evidence not supported by narrative"]

    involved_desc = conditions.get("involved_person_description")
    if involved_desc:
        if not _condition_words_match(narrative, involved_desc):
            return False, [f"person description '{involved_desc}' not visible in narrative"]
        reasons.append(f"person_description={involved_desc}")

    target_behavior = conditions.get("target_behavior")
    if target_behavior and not any(r.startswith(("fight_evidence", "fall_evidence", "normal_activity")) for r in reasons):
        if not _condition_words_match(narrative, target_behavior):
            return False, [f"target_behavior '{target_behavior}' not visible in narrative"]
        reasons.append(f"target_behavior={target_behavior}")

    return True, reasons


def _load_camera_location_map() -> dict[int, list[str]]:
    """Map camera IDs to human location labels used in natural-language rules.

    Configure with ANOMALY_CAMERA_LOCATION_MAP, for example:
      {"2": ["lab", "laboratory", "camera 2"]}

    We keep camera 2 -> lab as a safe project default because the current
    anomaly pipeline uses camera 2 for the lab demo.
    """
    default_map: dict[int, list[str]] = {2: ["lab", "laboratory"]}
    raw = os.getenv("ANOMALY_CAMERA_LOCATION_MAP")
    if not raw:
        return default_map
    try:
        data = json.loads(raw)
        parsed: dict[int, list[str]] = {}
        for key, value in data.items():
            labels = value if isinstance(value, list) else [value]
            parsed[int(key)] = [str(v).lower().strip() for v in labels if str(v).strip()]
        return parsed or default_map
    except Exception as e:
        log.warning("Invalid ANOMALY_CAMERA_LOCATION_MAP=%r: %s; using defaults", raw, e)
        return default_map


def _camera_location_labels(camera_id: int | None) -> set[str]:
    labels: set[str] = set()
    if camera_id is None:
        return labels
    labels.update({
        f"camera {camera_id}", f"cam {camera_id}", f"camera_id {camera_id}",
        f"camera-{camera_id}", f"cam-{camera_id}", f"camera{camera_id}", f"cam{camera_id}",
    })
    labels.update(_load_camera_location_map().get(int(camera_id), []))
    return {x.lower().strip() for x in labels if x}


def _narrative_has_visible_person(narrative: str) -> bool:
    n = (narrative or "").lower()
    if _contains_any(n, ["no person", "no people", "no individual", "no visible person"]):
        return False
    return _contains_any(
        n,
        [
            "person", "people", "individual", "human", "someone", "woman", "girl", "female",
            "man", "walking", "standing", "visible", "enters", "entering", "in the crop",
        ],
    )


def _rule_text_and_conditions(rule: dict[str, Any], conditions: dict[str, Any]) -> str:
    parts = [str(rule.get("rule_text") or "")]
    for key in ("location", "target_behavior", "involved_person_description", "person_type", "shirt_color", "clothing_color"):
        value = conditions.get(key)
        if value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _is_presence_or_entry_rule(rule: dict[str, Any], conditions: dict[str, Any], event_type: str) -> bool:
    """Detect rules like 'any person/girl enters the lab' or 'person visible in camera 2'."""
    rule_text = _rule_text_and_conditions(rule, conditions)
    # A clothing-only rule like "pink shirt visible" is not a general presence rule.
    if _rule_requires_color(rule, conditions):
        return False
    presence_terms = [
        "enter", "enters", "entered", "entering", "inside", "in the", "visible", "appears",
        "presence", "present", "seen", "detected", "walks into", "walk into",
    ]
    person_terms = ["person", "someone", "anyone", "people", "girl", "woman", "female", "man", "visitor"]
    return (
        event_type in {"intrusion", "other", "after_hours"}
        and any(t in rule_text for t in presence_terms)
        and any(t in rule_text for t in person_terms)
    )


def _should_presence_trigger_override_suppress(trigger_rules: list[dict[str, Any]]) -> bool:
    """Project demo policy: a matched lab-presence/intrusion trigger should not be
    cancelled by a generic normal-walking/standing suppress rule. If this rule is
    active, the security intent is 'any person in lab is alert-worthy'.
    """
    for r in trigger_rules:
        conditions = r.get("conditions") or {}
        if _is_presence_or_entry_rule(r, conditions, str(r.get("event_type") or "other")):
            return True
    return False


def match_rules_to_candidate(
    metadata: dict[str, Any],
    active_rules: list[dict[str, Any]],
    camera_id: int | None = None,
    narrative: str = "",
    window_start_ts: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deterministically pre-match rules before the LLM judgment.

    Conservative matching: fight rules require multi-person physical-contact
    evidence, fall rules require explicit fall/collapse evidence, clothing rules
    require the color to appear in the VLM narrative, and normal suppress rules
    require clearly normal activity.
    """
    trigger_rules: list[dict[str, Any]] = []
    suppress_rules: list[dict[str, Any]] = []

    candidate_reasons = metadata.get("candidate_reasons", []) or []
    inferred_events = _infer_events_from_text(narrative)

    if "high_speed" in candidate_reasons:
        inferred_events.add("sudden_movement")
    if "abrupt_direction_change" in candidate_reasons:
        inferred_events.add("sudden_movement")
    if "track_instability" in candidate_reasons and _has_sudden_movement_evidence(narrative):
        inferred_events.add("sudden_movement")
    if "distribution_score" in candidate_reasons and not inferred_events:
        inferred_events.add("other")

    event_hour = _parse_event_hour(window_start_ts or metadata.get("window_start_ts"))
    camera_tokens = _camera_location_labels(camera_id)
    person_visible = _narrative_has_visible_person(narrative)

    for rule in active_rules:
        rule_type = str(rule.get("rule_type") or "trigger").lower()
        event_type = str(rule.get("event_type") or "other")
        conditions = rule.get("conditions") or {}
        if not isinstance(conditions, dict):
            conditions = {}

        is_presence_rule = _is_presence_or_entry_rule(rule, conditions, event_type)

        # Event compatibility. Do not let `other` match every rule blindly; it is
        # okay for true presence rules and generic/manual rules, but visual checks
        # below still decide whether the rule is actually relevant.
        event_match = (
            event_type == "other"
            or event_type in inferred_events
            or (is_presence_rule and person_visible)
        )

        rule_location = str(conditions.get("location") or "All").lower().strip()
        rule_location_text = _rule_text_and_conditions(rule, conditions)
        if rule_location in {"", "all", "any", "anywhere"}:
            mentioned = sorted(tok for tok in camera_tokens if tok and tok in rule_location_text)
            location_match = True
            location_reason = f"location text matched {mentioned}" if mentioned else "location=all"
        elif camera_tokens and any(tok in rule_location for tok in camera_tokens):
            location_match = True
            location_reason = f"location matched camera_id={camera_id}"
        elif camera_tokens and any(tok in rule_location_text for tok in camera_tokens):
            location_match = True
            location_reason = f"rule text matched camera/location label for camera_id={camera_id}"
        else:
            location_match = False
            location_reason = f"location '{rule_location}' not mapped to camera_id={camera_id}; known={sorted(camera_tokens)}"

        time_match = True
        time_reason = "no time condition"
        time_range = conditions.get("time_range")
        if isinstance(time_range, dict) and time_range:
            if event_hour is None:
                time_match = False
                time_reason = "no event timestamp for time rule"
            else:
                after = time_range.get("after")
                before = time_range.get("before")
                checks: list[str] = []
                if after:
                    after_hour = int(str(after).split(":")[0])
                    time_match = time_match and event_hour >= after_hour
                    checks.append(f"event_hour={event_hour} >= {after_hour}")
                if before:
                    before_hour = int(str(before).split(":")[0])
                    time_match = time_match and event_hour <= before_hour
                    checks.append(f"event_hour={event_hour} <= {before_hour}")
                time_reason = ", ".join(checks) if checks else "time condition present"

        visual_match, visual_reasons = _visual_conditions_match(rule, conditions, event_type, narrative)
        if is_presence_rule and person_visible:
            visual_reasons.append("person_presence_visible=true")

        if event_match and location_match and time_match and visual_match:
            rule_copy = rule.copy()
            rule_copy["match_reason"] = "; ".join([
                f"event={event_type} inferred={sorted(inferred_events)}",
                location_reason,
                time_reason,
                *visual_reasons,
            ])
            if rule_type == "trigger":
                trigger_rules.append(rule_copy)
            else:
                suppress_rules.append(rule_copy)
        else:
            log.debug(
                "Rule %s not matched: event=%s location=%s time=%s visual=%s reasons=%s",
                rule.get("id"), event_match, location_match, time_match, visual_match, visual_reasons,
            )

    if _should_presence_trigger_override_suppress(trigger_rules):
        suppress_rules = [
            r for r in suppress_rules
            if not _is_normal_suppress_rule(r, r.get("conditions") or {})
        ]

    return trigger_rules, suppress_rules

def format_matched_rules(rules: list[dict[str, Any]], kind: str) -> str:
    """Format matched rules for LLM prompt"""
    if not rules:
        return f"  No {kind} rules matched"
    
    lines = []
    for i, r in enumerate(rules, 1):
        match_reason = r.get("match_reason", "")
        lines.append(
            f"  {i}. [ID={r.get('id')}] {r.get('rule_text')} "
            f"(matched: {match_reason})"
        )
    return "\n".join(lines)


def build_vlm_prompt(candidate_metadata: dict[str, Any]) -> str:
    score = candidate_metadata.get('final_score')
    threshold = candidate_metadata.get('threshold_value')
    reasons = candidate_metadata.get('candidate_reasons') or []
    motion = candidate_metadata.get('motion_stats') or {}

    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
    threshold_str = f"{threshold:.4f}" if isinstance(threshold, (int, float)) else str(threshold)
    ratio_str = ""
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)) and threshold > 0:
        ratio = score / threshold
        ratio_str = f" ({ratio:.2f}× threshold)"

    # Pull out the most relevant motion fields for the prompt
    motion_summary_keys = ["max_speed_norm", "avg_speed_norm", "max_turn_angle", "gap_count", "lost_frames", "track_instability"]
    motion_summary = {k: motion[k] for k in motion_summary_keys if k in motion}

    return f"""You are reviewing surveillance evidence flagged by a statistical anomaly detector.

ANOMALY SCORE CONTEXT:
  Distribution score : {score_str}{ratio_str}
  Threshold          : {threshold_str}
  Trigger reasons    : {reasons}
  Motion summary     : {json.dumps(motion_summary, ensure_ascii=False)}

The images below show:
  - IMAGE 1: A horizontal strip of person crop frames in temporal order (left → right over time).
  - IMAGE 2+: Scene/context frames showing wider area.

Your task:
Describe ONLY what is VISIBLE. Focus on:

PERSON ANALYSIS:
  - Gait: walking, running, stumbling, stationary?
  - Posture: upright, crouching, bent over, carrying something?
  - Actions: what is the person doing with their hands, body?

INTERACTION ANALYSIS (CRITICAL for multi-person scenes):
  - Number of people: How many people are visible in total (in person crops AND context frames)?
  - Physical contact: Any pushing, grabbing, hitting, restraining visible?
  - Confrontation indicators: Aggressive postures, defensive stances, rapid movements toward another person?
  - Victim/aggressor: Can you tell who initiated contact (if any)?
  - Person involvement: Is the tracked person (in the crop strip) actively involved in the interaction?

SCENE CONTEXT:
  - Environment: crowd, empty corridor, restricted area, etc.?
  - Objects: doors, equipment, furniture involvement?
  - Motion quality: smooth/continuous or abrupt/erratic?

IMPORTANT:
- Count ALL visible people carefully (person crops may show only one person, but context frames may show others)
- Do NOT speculate about intent, identity, or events not visible
- Do NOT dismiss physical contact as "dancing/playfulness" unless body language clearly supports it
- If uncertain about aggression vs. normal interaction, state the uncertainty explicitly
- Explicitly state if the visible motion appears COMPLETELY NORMAL for the scene

Provide a factual, detailed description."""


def build_llm_prompt(
    narrative: str,
    metadata: dict[str, Any],
    matched_trigger_rules: list[dict[str, Any]],
    matched_suppress_rules: list[dict[str, Any]]
) -> str:
    trigger_rules_text = format_matched_rules(matched_trigger_rules, "trigger")
    suppress_rules_text = format_matched_rules(matched_suppress_rules, "suppress")

    score = metadata.get('final_score')
    threshold = metadata.get('threshold_value')
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
    threshold_str = f"{threshold:.4f}" if isinstance(threshold, (int, float)) else str(threshold)
    ratio_note = ""
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)) and threshold > 0:
        ratio = score / threshold
        ratio_note = f" — {ratio:.2f}× above threshold" if ratio > 1 else f" — {ratio:.2f}× of threshold"

    allowed_trigger_ids = sorted(_allowed_rule_ids(matched_trigger_rules))
    allowed_suppress_ids = sorted(_allowed_rule_ids(matched_suppress_rules))

    return f"""You are the final anomaly reasoning judge for a surveillance system.

VLM FACTUAL NARRATIVE:
{narrative}

DISTRIBUTION AND GATE METADATA:
  Final score      : {score_str}{ratio_note}
  Threshold        : {metadata.get('threshold_name')} = {threshold_str}
  Candidate reasons: {metadata.get('candidate_reasons')}
  Priority         : {metadata.get('priority')}
  Motion stats     : {json.dumps(metadata.get('motion_stats') or {}, ensure_ascii=False)}

MATCHED TRIGGER RULES (behaviors that should produce alerts):
{trigger_rules_text}

MATCHED SUPPRESS RULES (behaviors that should suppress alerts):
{suppress_rules_text}

ALLOWED RULE IDS FOR OUTPUT:
  matched_trigger_rules may contain ONLY these IDs: {allowed_trigger_ids}
  matched_suppress_rules may contain ONLY these IDs: {allowed_suppress_ids}
  If no listed rule clearly applies, return an empty array. Never invent rule IDs.

DECISION INSTRUCTIONS:
1. Base your decision on the VLM narrative and matched rules — NOT on distribution score alone
2. The distribution score indicates statistical unusualness but is being calibrated
3. If matched suppress rules clearly apply to the described behavior → ALERT: NO
4. If matched trigger rules apply and behavior is clearly visible → ALERT: YES
4a. For intrusion/presence rules such as "any person/girl enters the lab", visible presence in the mapped location is enough; do not dismiss it just because movement is routine.
5. If NO rules match AND narrative shows only routine behavior → ALERT: NO (low confidence)
6. If high distribution score + concerning behavior in narrative but no rule → ALERT: YES (needs_review)
7. Physical confrontation indicators (pushing, hitting, grabbing) → ALERT: YES unless clearly playful
8. Multi-person interactions require careful analysis - uncertainty is acceptable

SEVERITY GUIDELINES:
- LOW: Minor deviations, unclear interactions, possible false positives
- MEDIUM: Rule-matched behaviors, moderate confidence concerns
- HIGH: Clear safety concerns, physical confrontations, matched high-priority triggers

EVENT TYPE (choose best match):
intrusion, loitering, after_hours, fall_detected, fight_detection, camera_tamper, 
sudden_movement, smoke_fire, crowd_detection, other

OUTPUT FORMAT (strict JSON, no markdown fences):
{{
  "alert_decision": "YES" or "NO",
  "severity": "LOW" or "MEDIUM" or "HIGH",
  "event_type": "one of the types above",
  "confidence": 0.0 to 1.0 (your confidence in this decision),
  "reason": "one clear sentence explaining the decision",
  "visual_evidence": "brief summary of what was actually seen",
  "uncertainty": "areas of doubt or ambiguity" or null,
  "matched_trigger_rules": [],
  "matched_suppress_rules": []
}}

For matched_trigger_rules and matched_suppress_rules, use ONLY the allowed rule IDs listed above.
Respond with ONLY the JSON object, no markdown, no prose, and no <think> tags."""


def mark_failed(conn: psycopg.Connection, job_id: int, error: str) -> None:
    conn.execute("BEGIN")
    conn.execute(
        "UPDATE reasoning_jobs SET status='failed', finished_at=now(), error=%s WHERE id=%s",
        (error, job_id),
    )
    conn.execute("COMMIT")


def determine_candidate_status(parsed_decision: dict[str, Any]) -> str:
    """
    Determine appropriate candidate status based on structured decision.
    
    Returns one of: alert_confirmed, dismissed_normal, needs_review, reasoning_failed
    """
    if parsed_decision.get("parse_error"):
        return "reasoning_failed"
    
    alert = parsed_decision.get("alert_decision", "NO")
    confidence = parsed_decision.get("confidence", 0.5)
    uncertainty = parsed_decision.get("uncertainty")
    
    if alert == "YES":
        if confidence >= 0.7:
            return "alert_confirmed"
        else:
            return "needs_review"
    else:  # NO
        if uncertainty or confidence < 0.6:
            return "needs_review"
        else:
            return "dismissed_normal"



def safe_update_candidate_status(conn: psycopg.Connection, candidate_id: int, preferred_status: str) -> str:
    """Update candidate status with fallback for older DB status constraints."""
    fallback = {
        "alert_confirmed": "resolved",
        "dismissed_normal": "discarded",
        "needs_review": "resolved",
        "reasoning_failed": "pending",
    }.get(preferred_status, "pending")

    conn.execute("SAVEPOINT candidate_status_update")
    try:
        conn.execute("UPDATE anomaly_candidates SET status=%s WHERE id=%s", (preferred_status, candidate_id))
        conn.execute("RELEASE SAVEPOINT candidate_status_update")
        return preferred_status
    except Exception as e:
        conn.execute("ROLLBACK TO SAVEPOINT candidate_status_update")
        log.warning("Could not use candidate status '%s' (%s); falling back to '%s'", preferred_status, e, fallback)
        conn.execute("UPDATE anomaly_candidates SET status=%s WHERE id=%s", (fallback, candidate_id))
        return fallback

def main() -> None:
    log.info("DB_DSN=%s", DB_DSN)
    log.info("OLLAMA_HOST=%s VLM=%s LLM=%s", OLLAMA_HOST, VLM_MODEL, LLM_MODEL)
    client = _client()

    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)
        while True:
            conn.execute("BEGIN")
            job = conn.execute(
                """
                SELECT id, anomaly_candidate_id, model_name, job_type, prompt, request_json
                FROM reasoning_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if not job:
                conn.execute("COMMIT")
                time.sleep(0.75)
                continue

            job_id, candidate_id, model_name, job_type, prompt, request_json = job
            request_json = _as_dict(request_json)
            conn.execute("UPDATE reasoning_jobs SET status='running', started_at=now() WHERE id=%s", (job_id,))
            conn.execute("COMMIT")

            try:
                if job_type == "vlm_reasoning":
                    metadata = request_json.get("candidate_metadata") or {}
                    person_bytes, context_bytes = resolve_candidate_images(request_json)
                    images = compose_vlm_images(person_bytes, context_bytes)
                    
                    # Fallback strategies if no images
                    if not images:
                        # Try representative frame only as last resort
                        rep_ref = request_json.get("representative_frame_ref")
                        if rep_ref:
                            try:
                                rep_bytes = fetch_jpeg_bytes(rep_ref)
                                if rep_bytes:
                                    images = [rep_bytes]
                                    log.info("VLM job %s: Using representative frame fallback", job_id)
                            except Exception as e:
                                log.warning("Representative frame fallback failed: %s", e)
                    
                    if not images:
                        mark_failed(conn, job_id, "No images/frames could be fetched for VLM reasoning")
                        continue

                    log.info(
                        "VLM job %s: %d person frames → 1 strip + %d context frames = %d total images",
                        job_id, len(person_bytes), len(context_bytes), len(images),
                    )
                    vlm_prompt = build_vlm_prompt(metadata)
                    
                    # VLM call with retry
                    narrative = ollama_generate(
                        client,
                        model=model_name or VLM_MODEL,
                        prompt=vlm_prompt,
                        images=images,
                        retry=OLLAMA_MAX_RETRIES
                    )
                    narrative = strip_model_reasoning(narrative)
                    
                    # Get active rules and match them
                    active_rules = request_json.get("active_rules")
                    if not active_rules:
                        rows = conn.execute(
                            """
                            SELECT id, rule_text, rule_type, event_type, conditions, source
                            FROM Anomaly_Rules
                            WHERE active = TRUE
                            ORDER BY id ASC
                            """
                        ).fetchall()
                        active_rules = [
                            {
                                "id": int(r[0]),
                                "rule_text": r[1],
                                "rule_type": r[2],
                                "event_type": r[3],
                                "conditions": r[4] or {},
                                "source": r[5],
                            }
                            for r in rows
                        ]
                    
                    camera_id = request_json.get("camera_id")
                    matched_triggers, matched_suppresses = match_rules_to_candidate(
                        metadata, active_rules, camera_id, narrative, request_json.get("window_start_ts")
                    )
                    
                    next_request = {
                        "narrative": narrative,
                        "candidate_metadata": metadata,
                        "matched_trigger_rules": matched_triggers,
                        "matched_suppress_rules": matched_suppresses,
                        "source_vlm_job_id": job_id,
                        "window_start_ts": request_json.get("window_start_ts"),
                        "window_end_ts": request_json.get("window_end_ts"),
                        "camera_id": camera_id,
                        "frames_used": len(images),
                        "person_frame_count": len(person_bytes),
                        "context_frame_count": len(context_bytes),
                    }
                    response_json = {
                        "narrative": narrative,
                        "frames_used": len(images),
                        "person_frame_count": len(person_bytes),
                        "context_frame_count": len(context_bytes),
                        "candidate_metadata": metadata,
                        "matched_trigger_rules": [r["id"] for r in matched_triggers],
                        "matched_suppress_rules": [r["id"] for r in matched_suppresses],
                    }

                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        UPDATE reasoning_jobs
                        SET status='succeeded', finished_at=now(), response_text=%s, response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (narrative, _json(response_json), job_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO reasoning_jobs (
                            anomaly_candidate_id, provider, model_name, job_type, prompt, request_json, status
                        )
                        VALUES (%s, 'ollama', %s, 'llm_reasoning', %s, %s::jsonb, 'queued')
                        """,
                        (candidate_id, LLM_MODEL, "Structured anomaly reasoning with matched rules", _json(next_request)),
                    )
                    conn.execute("COMMIT")

                elif job_type == "llm_reasoning":
                    narrative = str(request_json.get("narrative") or "")
                    metadata = request_json.get("candidate_metadata") or {}
                    matched_triggers = request_json.get("matched_trigger_rules") or []
                    matched_suppresses = request_json.get("matched_suppress_rules") or []
                    
                    final_prompt = build_llm_prompt(narrative, metadata, matched_triggers, matched_suppresses)
                    
                    # LLM call with retry
                    decision = ollama_chat(
                        client,
                        model=model_name or LLM_MODEL,
                        prompt=final_prompt,
                        retry=OLLAMA_MAX_RETRIES
                    )
                    decision = strip_model_reasoning(decision)
                    
                    # Parse structured decision and remove invented rule IDs
                    parsed = parse_structured_decision(decision, matched_triggers, matched_suppresses)
                    
                    # Determine appropriate candidate status
                    candidate_status = determine_candidate_status(parsed)
                    
                    response_json = {
                        "narrative": narrative,
                        "decision_text": decision,
                        "structured_decision": parsed,
                        "candidate_metadata": metadata,
                        "matched_trigger_rules": matched_triggers,
                        "matched_suppress_rules": matched_suppresses,
                        "frames_used": request_json.get("frames_used", 0),
                        "person_frame_count": request_json.get("person_frame_count", 0),
                        "context_frame_count": request_json.get("context_frame_count", 0),
                    }

                    conn.execute("BEGIN")
                    if parsed.get("parse_error"):
                        conn.execute(
                            """
                            UPDATE reasoning_jobs
                            SET status='failed', finished_at=now(), response_text=%s, response_json=%s::jsonb, error=%s
                            WHERE id=%s
                            """,
                            (decision, _json(response_json), parsed.get("parse_error"), job_id),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE reasoning_jobs
                            SET status='succeeded', finished_at=now(), response_text=%s, response_json=%s::jsonb
                            WHERE id=%s
                            """,
                            (decision, _json(response_json), job_id),
                        )
                    
                    # Update candidate with new status system; fall back if DB status constraint is older.
                    actual_status = safe_update_candidate_status(conn, candidate_id, candidate_status)
                    response_json["candidate_status"] = actual_status
                    
                    # Try to update decision columns if they exist
                    conn.execute("SAVEPOINT decision_columns")
                    try:
                        conn.execute(
                            """
                            UPDATE anomaly_candidates
                            SET alert_decision=%s, severity=%s, decision_reason=%s, resolved_at=now()
                            WHERE id=%s
                            """,
                            (
                                parsed.get("alert_decision"),
                                parsed.get("severity"),
                                parsed.get("reason"),
                                candidate_id
                            ),
                        )
                        conn.execute("RELEASE SAVEPOINT decision_columns")
                    except Exception:
                        conn.execute("ROLLBACK TO SAVEPOINT decision_columns")
                    
                    conn.execute("COMMIT")

                else:
                    mark_failed(conn, job_id, f"Unknown reasoning job_type: {job_type}")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                try:
                    mark_failed(conn, job_id, str(e))
                except Exception as inner:
                    log.error("Failed to mark job %s as failed: %s", job_id, inner)


if __name__ == "__main__":
    main()