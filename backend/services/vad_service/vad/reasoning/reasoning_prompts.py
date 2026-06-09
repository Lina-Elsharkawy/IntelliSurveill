"""
reasoning_prompts.py
====================
Prompt builders for the 3-phase Perception → Cognition → Guardrails pipeline.

Key design changes (paper-backed):
────────────────────────────────────────────────────────────────────────────────
[1] VLM HALLUCINATION FIX  (ASK-Hint, arXiv:2510.02155)
    The word "anomaly" (and synonyms like "unusual", "suspicious", "abnormal")
    must NEVER appear in the VLM prompt.  Zhang et al. showed that prompting a
    VLM with anomaly vocabulary triggers visual-textual co-occurrence shortcuts —
    the model agrees with the word "anomaly" regardless of what it sees, causing
    ~30% AUC degradation.  Instead the VLM receives specific action-grounded
    questions derived from the active rule set (e.g. "is a person lying on the
    floor?", "are two people in close physical contact?").

[2] VLM AS CAPTIONER ONLY  (LAVAD, CVPR 2024, arXiv:2404.01014)
    The VLM's only job is to caption what it sees.  It never scores, never
    decides, never sees rule logic.  Decision-making is fully delegated to the
    LLM layer.

[3] LLM RULES-ONLY DECISION  (AnomalyRuler, ECCV 2024, arXiv:2407.10299)
    The LLM receives the VLM caption PLUS the full active Anomaly_Rules table.
    Anomaly_Rules is the single source of truth.
    It must answer YES/NO/UNCERTAIN by matching the caption against rules.
    OPEN_SET_VISUAL_ANOMALY is removed: the Unified Framework (NeurIPS 2025,
    arXiv:2511.00962) showed that unrestricted open-set reasoning introduces
    content weakly related to true anomalies and increases false positives.

[4] FRAME BUDGET  (Holmes-VAD, ReCoVAD, AnyAnomaly)
    6–8 keyframes is the recommended budget. The keyframe_selector module
    handles the 24→8 reduction using sparse CLIP/diversity selection.
    The VLM prompt explicitly states the frame count and their role.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
from typing import Any

from ..json_utils import sanitize_json
from .reasoning_schema import DeepReasoningContext, PoseReasoningContext, VlmVisualReview, model_to_dict


def _json(obj: Any, max_chars: int = 9000) -> str:
    text = json.dumps(sanitize_json(obj), ensure_ascii=False, indent=2, default=str, allow_nan=False)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...<truncated>"


# ─────────────────────────────────────────────────────────────────────────────
# Rule translation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rule_to_visual_question(rule: dict[str, Any]) -> str:
    """Convert one active rule into a specific, action-grounded visual question.

    This implements the ASK-Hint insight: instead of asking broad judgement questions, ask concrete questions like
    "is a person lying on the floor?" or "are two people in physical contact?".
    The VLM answers with visual facts, not policy labels.
    """
    rule_text = (
        rule.get("rule_text")
        or rule.get("rule_name")
        or rule.get("name")
        or rule.get("description")
        or ""
    ).strip()
    event_type = (rule.get("event_type") or rule.get("rule_type") or "").strip().lower()
    conditions = rule.get("conditions") or {}

    location = str(conditions.get("location") or "the scene").strip()
    if location.lower() in {"all", "any", ""}:
        location = "the scene"

    # Map structured event types → concrete visual observation questions.
    question_map = {
        "fall_detected":    "Is any person falling, collapsed, lying on the floor, or in a very low uncontrolled posture?",
        "fight_detection":  "Are two or more people in close physical contact — hitting, pushing, shoving, grappling, or struggling?",
        "intrusion":        f"Is a person present in a restricted area or near secured access points in {location}?",
        "loitering":        f"Is a person standing still for an extended time without an obvious task in {location}?",
        "after_hours":      f"Is a person present in {location} when the area should be unoccupied?",
        "sudden_movement":  "Is any person running, sprinting, or moving at very high speed?",
        "camera_tamper":    "Is the camera view being blocked, covered, or physically disturbed?",
        "smoke_fire":       "Is there visible smoke, flame, or fire in the scene?",
        "crowd_detection":  f"Are more than two people gathered in a group in {location}?",
        "person_on_floor":  "Is any person lying or sitting on the floor in an uncontrolled posture?",
        "physical_altercation": "Are two or more people in direct physical conflict or aggressive contact?",
        "pushing_or_shoving":   "Is one person pushing, shoving, or forcibly moving another person?",
        "grappling_or_wrestling": "Are two people locked in a grapple, hold, or wrestling posture?",
        "fall_or_collapse":     "Is any person falling, stumbling, or collapsing to the ground?",
        "unsafe_equipment_interaction": "Is a person interacting with equipment in an visibly risky or uncontrolled way?",
        "rapid_unusual_movement": "Is any person making rapid, jerky, or uncontrolled movements?",
        "possible_intrusion_or_security_event": "Is there evidence of unauthorized entry or restricted-entry or access-control activity?",
    }

    # Try structured event_type first.
    for key, question in question_map.items():
        if key in event_type or event_type in key:
            # Augment with person description from conditions if present.
            person_desc = conditions.get("involved_person_description") or conditions.get("clothing_color")
            if person_desc:
                question += f" Focus on a person matching: {person_desc}."
            return question

    # Fallback: convert the raw rule text into a yes/no observation question.
    if rule_text:
        # Strip trigger/suppress framing words to get the observable behaviour.
        clean = rule_text
        for prefix in [
            "alert me if", "alert if", "tell me if", "notify if",
            "do not alert if", "ignore if", "suppress if", "do not notify if",
        ]:
            if clean.lower().startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        return f"Can you observe the following in this video sequence: {clean}?"

    return "Describe all visible people, their postures, movements, and interactions in detail."


def build_vlm_observation_hints(active_rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Build perception-only observation hints for the VLM from the active rule set.

    Each hint becomes a specific visual question (ASK-Hint methodology) rather than
    an abstract anomaly label.  The VLM is never told whether a rule is a trigger or
    suppress rule — that distinction is for the LLM only.
    """
    hints: list[dict[str, Any]] = []
    seen_questions: set[str] = set()

    for rule in active_rules or []:
        if rule.get("active") is False:
            continue
        question = _rule_to_visual_question(rule)
        if question in seen_questions:
            continue
        seen_questions.add(question)
        hints.append({
            "observation_question": question,
            "event_category": rule.get("event_type") or rule.get("rule_type") or "unspecified",
        })
    return hints


def _format_rules_for_llm(active_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format active rules for the LLM cognition layer.

    Uses Anomaly_Rules table rules as the single source of truth.
    The LLM sees rule_id, rule_type (trigger/suppress), event_type,
    conditions, and a human-readable description.
    This is the AnomalyRuler design: the LLM must match captions to rules
    rather than reason freely.
    """
    formatted = []
    for rule in active_rules or []:
        if rule.get("active") is False:
            continue
        formatted.append({
            "rule_id": rule.get("id") or rule.get("rule_id") or "?",
            "rule_name": rule.get("rule_name") or rule.get("name") or rule.get("rule_text") or "",
            "rule_type": rule.get("rule_type") or "trigger",
            "event_type": rule.get("event_type") or "",
            "event_types": rule.get("event_types") or [rule.get("event_type")] if rule.get("event_type") else [],
            "conditions": rule.get("conditions") or {},
            "description": rule.get("description") or rule.get("rule_text") or "",
            "effect": rule.get("effect") or {},
        })
    return formatted


# ─────────────────────────────────────────────────────────────────────────────
# VLM Prompt — Deep Gate
# ─────────────────────────────────────────────────────────────────────────────

def build_deep_vlm_visual_prompt(
    ctx: DeepReasoningContext,
    visual_observation_hints: list[dict[str, Any]] | None = None,
) -> str:
    """Build the VLM caption prompt for a Deep gate candidate event.

    ASK-Hint fix: no anomaly vocabulary. The VLM only answers specific
    action questions derived from the active rule set, then provides a
    factual scene caption. Decision-making is fully delegated to the LLM.
    """
    n_frames = len(ctx.evidence_object_keys)
    hints = visual_observation_hints or []

    # Build numbered observation questions from hints.
    if hints:
        questions_block = "\n".join(
            f"  Q{i+1}: {h['observation_question']}"
            for i, h in enumerate(hints)
        )
    else:
        questions_block = "  Q1: Describe what each visible person is doing in as much detail as possible."

    return f"""You are a video captioning assistant. Your task is to describe what you see in a sequence of {n_frames} video frames from a fixed security camera.

IMPORTANT RULES:
- Describe only what you can directly observe. Do not guess, infer intent, or make judgements.
- You are a witness, not a judge: do NOT decide whether the event is an alert, anomaly, threat, fight, or suspicious activity.
- Do NOT output alert_decision, visual_decision, severity, event_type, or final_action. Those fields belong only to the LLM/Python rule stages.
- Describe body posture, limb positions, movement direction, speed, proximity, and physical contact in concrete terms.
- Compare early frames (first third) to middle frames to late frames (last third) to describe how the scene changes.

OBSERVATION QUESTIONS — answer each one based only on what is visible:
{questions_block}

Metadata (for reference only, do not use in caption):
{_json({
    "event_id": ctx.event_id,
    "tracker_track_id": ctx.tracker_track_id,
    "gate": ctx.gate_name,
    "stream_key": ctx.stream_key,
}, 600)}

Scene context:
{_json(ctx.scene_context, 1200)}

Frame sequence ({n_frames} frames, chronological order):
{_json(ctx.evidence_object_keys, 1200)}

Return ONLY valid JSON matching this exact structure. No markdown. No null values.

{{
  "schema_version": "1.0",
  "review_type": "vlm_visual_review",
  "observation_status": "OBSERVED | NOT_OBSERVED | UNCLEAR",
  "dominant_visible_activity": "Neutral short label such as walking, standing, sitting, lying_on_floor, object_interaction, person_contact, unclear_view. Do not use anomaly labels.",
  "visual_confidence": 0.0,
  "image_quality": "GOOD | FAIR | POOR | UNUSABLE",
  "evidence_sufficiency": "SUFFICIENT | PARTIAL | INSUFFICIENT",
  "visible_scene": "One sentence describing the room, setting, and fixed objects visible.",
  "person_observation": "Describe each visible person: their location in frame, posture, what body parts are doing, and distance to other people. Use only observable facts.",
  "motion_observation": "Describe how the scene changes from early frames to middle frames to late frames. Note direction, speed, and any change in posture or contact.",
  "observation_answers": {{
    "Q1": "Direct factual answer to observation question 1.",
    "Q2": "Direct factual answer to observation question 2 (if present)."
  }},
  "rule_relevant_visual_facts": [
    "List only concrete visible facts that would need a rule to evaluate — e.g. 'person lying flat on floor', 'two people in direct physical contact'. Empty list if none."
  ],
  "normality_evidence": [
    "List concrete visible facts that indicate ordinary activity — e.g. 'person walking at normal pace', 'person seated at desk'. Empty list if none."
  ],
  "false_positive_risks": [
    "List visual limitations: occlusion, motion blur, camera angle, partial body visible, low resolution."
  ],
  "observation_summary": "State in one sentence what the dominant visible activity is, using only observable facts. Do not judge whether it is normal, abnormal, suspicious, or dangerous."
}}

Output rules:
- observation_status OBSERVED: you can clearly describe at least one concrete visual fact in rule_relevant_visual_facts or normality_evidence.
- observation_status NOT_OBSERVED: the requested observation questions are clearly not visible.
- observation_status UNCLEAR: image quality, occlusion, distance, or ambiguity prevents a reliable description.
- visual_confidence: your confidence in the accuracy of your visual description (0.0–1.0), not in any rule judgement.
- dominant_visible_activity must be a neutral activity label only. Do not output policy labels such as physical altercation, anomaly, suspicious, threat, alert, severity, or decision.
- Do NOT use gate names, model names, or score values as evidence.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# VLM Prompt — Pose Gate
# ─────────────────────────────────────────────────────────────────────────────

def build_pose_vlm_visual_prompt(
    ctx: PoseReasoningContext,
    visual_observation_hints: list[dict[str, Any]] | None = None,
) -> str:
    """Build the VLM caption prompt for a Pose gate candidate event.

    Same ASK-Hint design as the Deep prompt. Pose-specific instruction:
    focus on articulation — joint angles, limb positions, torso inclination,
    bilateral symmetry, contact points.
    """
    n_frames = len(ctx.evidence_object_keys)
    hints = visual_observation_hints or []

    if hints:
        questions_block = "\n".join(
            f"  Q{i+1}: {h['observation_question']}"
            for i, h in enumerate(hints)
        )
    else:
        questions_block = "  Q1: Describe the posture and limb positions of each visible person in detail across all frames."

    return f"""You are a video captioning assistant specializing in human body posture and movement. Your task is to describe what you see in a sequence of {n_frames} video frames.

IMPORTANT RULES:
- Describe only what you can directly observe. Do not guess, infer intent, or make judgements.
- You are a witness, not a judge: do NOT decide whether the event is an alert, anomaly, threat, fight, or suspicious activity.
- Do NOT output alert_decision, visual_decision, severity, event_type, or final_action. Those fields belong only to the LLM/Python rule stages.
- Focus specifically on: joint positions (shoulders, elbows, wrists, hips, knees, ankles), torso angle, bilateral symmetry, speed of limb movement, and contact with other people or objects.
- Compare early frames (first third) to middle frames to late frames (last third) to describe how posture changes.

OBSERVATION QUESTIONS — answer each one based only on what is visible:
{questions_block}

Metadata (for reference only):
{_json({
    "event_id": ctx.event_id,
    "tracker_track_id": ctx.tracker_track_id,
    "gate": ctx.gate_name,
    "stream_key": ctx.stream_key,
}, 600)}

Scene context:
{_json(ctx.scene_context, 1200)}

Frame sequence ({n_frames} frames, chronological order):
{_json(ctx.evidence_object_keys, 1200)}

Return ONLY valid JSON matching this exact structure. No markdown. No null values.

{{
  "schema_version": "1.0",
  "review_type": "vlm_visual_review",
  "observation_status": "OBSERVED | NOT_OBSERVED | UNCLEAR",
  "dominant_visible_activity": "Neutral short label such as walking, standing, sitting, lying_on_floor, object_interaction, person_contact, unclear_view. Do not use anomaly labels.",
  "visual_confidence": 0.0,
  "image_quality": "GOOD | FAIR | POOR | UNUSABLE",
  "evidence_sufficiency": "SUFFICIENT | PARTIAL | INSUFFICIENT",
  "visible_scene": "One sentence describing the room and setting.",
  "person_observation": "Describe each visible person: torso angle, arm positions, leg positions, whether they are upright or not, and whether they are in contact with another person or object.",
  "motion_observation": "Describe how body posture changes from early frames to middle frames to late frames. Include direction of movement and speed estimate (slow / moderate / fast).",
  "observation_answers": {{
    "Q1": "Direct factual answer to observation question 1.",
    "Q2": "Direct factual answer to observation question 2 (if present)."
  }},
  "rule_relevant_visual_facts": [
    "List only concrete posture/movement facts that would need a rule to evaluate — e.g. 'person torso horizontal, face toward floor', 'rapid arm extension toward second person'. Empty list if none."
  ],
  "normality_evidence": [
    "List concrete posture/movement facts indicating ordinary activity — e.g. 'upright walking posture', 'arms at sides, slow pace'. Empty list if none."
  ],
  "false_positive_risks": [
    "List visual limitations: partial occlusion, body part cut off by frame edge, low keypoint visibility, perspective distortion."
  ],
  "observation_summary": "State in one sentence what the dominant visible body activity is, using only observable facts. Do not judge whether it is normal, abnormal, suspicious, or dangerous."
}}

Output rules:
- observation_status OBSERVED: you can clearly describe at least one concrete posture/movement fact in rule_relevant_visual_facts or normality_evidence.
- observation_status NOT_OBSERVED: the requested posture/movement observations are clearly not visible.
- observation_status UNCLEAR: image quality, occlusion, distance, or ambiguity prevents a reliable posture description.
- visual_confidence: your confidence in the accuracy of your posture description (0.0–1.0), not in any rule judgement.
- dominant_visible_activity must be a neutral activity label only. Do not output policy labels such as physical altercation, anomaly, suspicious, threat, alert, severity, or decision.
- Do NOT use pose score, threshold, GMM distance, or statistical values as evidence.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# LLM Policy Prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_llm_policy_prompt(
    *,
    ctx: DeepReasoningContext | PoseReasoningContext,
    vlm_review: VlmVisualReview,
    active_rules: list[dict[str, Any]],
) -> str:
    """Build the LLM rule-matching prompt.

    Design (AnomalyRuler, ECCV 2024):
    - The LLM receives the VLM caption plus the COMPLETE active rule set.
    - The active rule set comes from Anomaly_Rules only: trigger rules create alerts,
      suppress rules silence known benign cases.
    - The LLM must match the caption to rules. It must NOT invent evidence or
      reason beyond what the VLM caption says.
    - OPEN_SET_VISUAL_ANOMALY is removed per the Unified Framework finding
      that unrestricted open-set reasoning increases false positives.
    - The LLM follows a 4-step CoT chain (VAD-R1, NeurIPS 2025):
        Step 1: identify observable actions from the VLM caption.
        Step 2: check each trigger rule — does the caption match?
        Step 3: check each suppress rule — does the caption match?
        Step 4: synthesise final decision.
    """
    gate_context: dict[str, Any] = {
        "event_id": ctx.event_id,
        "case_id": ctx.case_id,
        "gate_name": ctx.gate_name,
        "score_ratio": ctx.score_ratio,
        "ratio_band": ctx.ratio_band(),
        "stream_key": ctx.stream_key,
        "camera_key": ctx.camera_key,
        "tracker_track_id": ctx.tracker_track_id,
    }
    if getattr(ctx, "gate_name", "deep") == "pose":
        gate_context["pose_score"] = getattr(ctx, "pose_score", None)
        gate_context["threshold_value"] = ctx.threshold_value
    else:
        gate_context["deep_score"] = getattr(ctx, "deep_score", None)
        gate_context["threshold_value"] = ctx.threshold_value

    formatted_rules = _format_rules_for_llm(active_rules)
    trigger_rules = [r for r in formatted_rules if str(r.get("rule_type", "")).lower() == "trigger"]
    suppress_rules = [r for r in formatted_rules if str(r.get("rule_type", "")).lower() in {"suppress", "benign", "normal"}]

    # Build a plain-English rule summary to help small LLMs.
    def _rule_summary(rules: list[dict]) -> str:
        lines = []
        for r in rules:
            name = r.get("rule_name") or r.get("description") or f"Rule {r.get('rule_id')}"
            event = r.get("event_type") or ""
            cond = r.get("conditions") or {}
            loc = cond.get("location") or "anywhere"
            time_r = cond.get("time_range")
            time_str = f" (time: {time_r})" if time_r else ""
            person = cond.get("involved_person_description") or cond.get("person_type") or ""
            person_str = f", person: {person}" if person else ""
            lines.append(f"  [{r.get('rule_id')}] {name} — event: {event}, location: {loc}{time_str}{person_str}")
        return "\n".join(lines) if lines else "  (none)"

    return f"""You are a surveillance rule-matching engine. A video captioning model has described what it observed in a video clip. Your task is to decide whether those observations match any active surveillance rules.

You did NOT see the video. You must work ONLY from the caption below. Do not invent new visual facts.

─── GATE CONTEXT ────────────────────────────────────────────────────────────
{_json(gate_context, 1200)}

Score ratio guidance:
- score_ratio < 1.15 (weak): require strong, unambiguous rule match before YES.
- score_ratio 1.15–1.50 (moderate): standard rule matching applies.
- score_ratio > 1.50 (strong): rule match with partial caption evidence may be sufficient.

─── VLM VISUAL CAPTION ──────────────────────────────────────────────────────
{_json(model_to_dict(vlm_review), 5000)}

─── ACTIVE TRIGGER RULES (alert when matched) ───────────────────────────────
{_rule_summary(trigger_rules)}

Full trigger rule details:
{_json(trigger_rules, 4000)}

─── ACTIVE SUPPRESS RULES (do NOT alert when matched) ───────────────────────
{_rule_summary(suppress_rules)}

Full suppress rule details:
{_json(suppress_rules, 2500)}

─── REASONING PROCEDURE (follow all 4 steps) ────────────────────────────────
Step 1 — Extract observable actions:
  List the concrete actions and postures described in the VLM caption.
  Do not add anything not in the caption.

Step 2 — Check trigger rules:
  For each trigger rule: does the caption describe the event_type and conditions?
  A rule MATCHES only if: (a) the event_type is clearly described in the caption,
  AND (b) location/time/person conditions are consistent with the caption or
  are "All"/"any" (unconstrained).

Step 3 — Check suppress rules:
  For each suppress rule: does the caption describe the suppressed behavior?
  If a suppress rule matches, it overrides a trigger rule UNLESS the trigger
  rule has stronger visual evidence (e.g., direct physical contact vs. possible
  proximity).

Step 4 — Final decision:
  - YES: at least one trigger rule matched with concrete caption evidence, AND
    no suppress rule clearly overrides it.
  - NO: no trigger rule matched, OR a suppress rule clearly overrides all triggers.
  - UNCERTAIN: caption is ambiguous, image quality is poor, or evidence is
    insufficient to confirm or deny a trigger rule match.
  
  NOTE: The VLM is only a neutral visual witness. It does not make an alert decision.
  Do not treat any VLM observation_status as a policy decision. Score ratio alone is never sufficient for YES.

─── OUTPUT FORMAT ────────────────────────────────────────────────────────────
Return ONLY valid JSON. No markdown. No explanation outside the JSON.

{{
  "schema_version": "1.0",
  "review_type": "llm_policy_review",
  "policy_alert_decision": "YES | NO | UNCERTAIN",
  "policy_severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "policy_confidence": 0.0,
  "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
  "score_assessment": {{
    "score_ratio": 0.0,
    "ratio_band": "weak | moderate | strong",
    "score_reasoning": "One sentence on how the score ratio affects confidence."
  }},
  "step1_observable_actions": [
    "List the concrete actions/postures from the VLM caption only."
  ],
  "matched_trigger_rules": [
    {{
      "rule_id": "exact rule_id from the trigger rules list above",
      "rule_name": "exact rule_name",
      "applied": true,
      "reason": "Quote the specific caption text that matches this rule's event_type and conditions."
    }}
  ],
  "matched_suppress_rules": [
    {{
      "rule_id": "exact rule_id from the suppress rules list above",
      "rule_name": "exact rule_name",
      "applied": true,
      "reason": "Quote the specific caption text that matches this suppress rule."
    }}
  ],
  "rule_reasoning": [
    "Step 2 finding for trigger rules.",
    "Step 3 finding for suppress rules.",
    "Step 4 synthesis."
  ],
  "evidence_assessment": {{
    "uses_only_vlm_evidence": true,
    "has_strong_visual_anomaly_evidence": false,
    "has_normality_evidence": false,
    "has_false_positive_risk": false
  }},
  "decision_reason": "One paragraph: state which rule was matched (or not matched), which caption evidence supports it, and why that leads to the final decision.",
  "limitations": [
    "List any ambiguity, occlusion, weak score ratio, or evidence gaps."
  ]
}}

Constraints:
- policy_confidence must be between 0.0 and 1.0.
- If policy_alert_decision is YES, matched_trigger_rules must contain at least one entry with applied=true.
- If no trigger rule is matched, policy_alert_decision must be NO or UNCERTAIN.
- Do not create new rule_ids. Only reference rule_ids from the lists above.
- Output JSON only.
""".strip()