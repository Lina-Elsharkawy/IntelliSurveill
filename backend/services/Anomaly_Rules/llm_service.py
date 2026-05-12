import json
import ollama
import time
from typing import Literal
from config import OLLAMA_HOST, LLM_MODEL
from spellchecker import SpellChecker

ALLOWED_EVENT_TYPES = [
    "intrusion", "loitering", "after_hours", "fall_detected", 
    "fight_detection", "camera_tamper", "sudden_movement", 
    "smoke_fire", "crowd_detection", "other"
]


OLLAMA_TIMEOUT_SEC = 120


def _client() -> ollama.Client:
    try:
        return ollama.Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SEC)
    except TypeError:
        return ollama.Client(host=OLLAMA_HOST)

def correct_spelling(text: str) -> str:
    """Light spelling correction without damaging domain-specific rule words."""
    protected = {
        "loitering", "after_hours", "fight", "fighting", "scrfd", "arcface",
        "pink", "blue", "red", "yellow", "green", "black", "white", "gray", "grey",
        "cafeteria", "hallway", "corridor", "server", "room"
    }
    spell = SpellChecker()
    words = text.split()
    corrected = []
    for word in words:
        stripped = word.strip(".,!?;:\"'()[]{}")
        if not stripped:
            corrected.append(word)
            continue
        if stripped.lower() in protected or any(ch.isdigit() for ch in stripped):
            corrected.append(word)
            continue
        suggestion = spell.correction(stripped)
        corrected.append(word if not suggestion else word.replace(stripped, suggestion, 1))
    return " ".join(corrected)

def parse_rule_with_llm(rule_text: str, rule_type: Literal["trigger", "suppress"]) -> dict:
    """
    Call LLM to convert natural language rule into structured JSON with extended schema.
    
    Extended schema now supports:
    - clothing_color, shirt_color
    - involved_person_description
    - number_of_people
    - interaction_type (physical_contact, confrontation, etc.)
    - target_behavior
    - severity_override
    """
    
    client = _client()
    rule_text = correct_spelling(rule_text)

    prompt = f"""You are a rule parser for a surveillance system.
Convert the following admin rule into a structured JSON object.

RULE TYPE: {rule_type} (trigger = alert on this, suppress = ignore this)

ALLOWED event_type values (choose the BEST match):
- "intrusion"         → unauthorized access, trespassing, entering restricted area
- "loitering"         → hanging around, standing still, suspicious waiting  
- "after_hours"       → presence outside business hours, after 5pm, late night
- "fall_detected"     → person falling down, collapse, trip
- "fight_detection"   → fighting, physical altercation, violence, brawl, combat, pushing, hitting
- "camera_tamper"     → camera blocked, covered, moved, vandalized
- "sudden_movement"   → running, sprinting, rapid movement
- "smoke_fire"        → smoke, fire, flames, burning
- "crowd_detection"   → crowd, gathering, large group, many people
- "other"             → Use for unique behaviors not covered above (drinking, eating, sleeping, etc.)

EXTENDED CONDITIONS (extract if mentioned):
- location: specific room/area or "All"
- time_range: {{"after": "HH:MM", "before": "HH:MM"}} or null
- person_type: "employee", "visitor", "security", "anyone", or null
- clothing_color: if person's clothing color is mentioned (e.g. "pink", "red", "blue")
- shirt_color: if shirt color specifically mentioned
- involved_person_description: description of person involved (e.g. "person in pink shirt")
- number_of_people: number if specified (e.g. 2, "multiple", "group")
- interaction_type: "physical_contact", "confrontation", "normal", or null
- target_behavior: specific behavior to detect/ignore
- severity_override: "LOW", "MEDIUM", "HIGH" if specified, else null

IMPORTANT:
- If parsing fails or event type is unclear, use "other" instead of defaulting to "intrusion"
- For physical confrontation rules, use event_type="fight_detection"
- Extract person descriptions carefully (e.g. "person in pink shirt" → involved_person_description)

EXAMPLES:

Example 1 - trigger with clothing:
Admin rule: "Alert if the person in the pink shirt is involved in physical confrontation"
Output:
{{
  "rule_text": "Alert if the person in the pink shirt is involved in physical confrontation",
  "event_type": "fight_detection",
  "conditions": {{
    "location": "All",
    "time_range": null,
    "person_type": null,
    "clothing_color": "pink",
    "shirt_color": "pink",
    "involved_person_description": "person in pink shirt",
    "number_of_people": 2,
    "interaction_type": "physical_contact",
    "target_behavior": "physical confrontation"
  }}
}}

Example 2 - suppress normal behavior:
Admin rule: "Do not alert if someone is drinking coffee in the break room"
Output:
{{
  "rule_text": "Do not alert if someone is drinking coffee in the break room",
  "event_type": "other",
  "conditions": {{
    "location": "break room",
    "time_range": null,
    "person_type": null,
    "target_behavior": "drinking coffee"
  }}
}}

Example 3 - intrusion after hours:
Admin rule: "Alert me if someone enters the server room after 5 PM"
Output:
{{
  "rule_text": "Alert me if someone enters the server room after 5 PM",
  "event_type": "intrusion",
  "conditions": {{
    "location": "server room",
    "time_range": {{"after": "17:00"}},
    "person_type": "anyone"
  }}
}}

Example 4 - crowd with number:
Admin rule: "Ignore crowd alerts in the cafeteria between 12 PM and 2 PM"
Output:
{{
  "rule_text": "Ignore crowd alerts in the cafeteria between 12 PM and 2 PM",
  "event_type": "crowd_detection",
  "conditions": {{
    "location": "cafeteria",
    "time_range": {{"after": "12:00", "before": "14:00"}},
    "number_of_people": "multiple"
  }}
}}

Output ONLY valid JSON. No explanation. No markdown.

Admin rule: "{rule_text}"
"""
    for attempt in range(3):
        try:
            resp = client.chat(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.0, "num_ctx": 4096}
            )

            raw = (resp.get("message") or {}).get("content", "").strip()

            # Strip markdown fences if model adds them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)

            # Validate event_type is from allowed list
            if parsed.get("event_type") not in ALLOWED_EVENT_TYPES:
                # Use "other" instead of defaulting to "intrusion"
                parsed["event_type"] = "other"

            # Ensure conditions dict exists
            if "conditions" not in parsed or not isinstance(parsed["conditions"], dict):
                parsed["conditions"] = {}

            return parsed
        except Exception as e:
            print(f"LLM parse error (attempt {attempt+1}): {e}")
            if attempt == 2:
                # Safe fallback if all attempts fail - use "other" not "intrusion"
                return {
                    "rule_text": rule_text,
                    "event_type": "other",
                    "conditions": {
                        "location": "All",
                        "time_range": None,
                        "person_type": None
                    }
                }
            time.sleep(1)


# In-memory cache for semantic comparisons
SEMANTIC_CACHE = {}

def _llm_same_subject(rule_a: dict, rule_b: dict) -> tuple[bool, str]:
    """
    Since small LLMs (like qwen2.5:3b) can be unreliable for logical comparisons,
    we use a robust hybrid approach with in-memory caching.
    """
    text1 = rule_a.get('rule_text', '').lower().strip()
    text2 = rule_b.get('rule_text', '').lower().strip()

    # Sort keys to ensure (A, B) and (B, A) share the same cache entry
    cache_key = tuple(sorted([text1, text2]))
    if cache_key in SEMANTIC_CACHE:
        return SEMANTIC_CACHE[cache_key]

    stop_words = {
        'if', 'a', 'the', 'is', 'are', 'me', 'alert', 'do', 'not', 'no',
        'tell', 'notify', 'when', 'there', 'someone', 'anyone', 'in',
        'at', 'on', 'and', 'or', 'that', 'this', 'for', 'to', 'of',
        'person', 'people', 'employee', 'employees', 'student', 'worker', 'must', 'be',
        'wearing', 'wear', 'wears', 'carrying', 'carry', 'carries',
        'holding', 'hold', 'holds', 'using', 'use', 'uses', 'has', 'have',
        'enters', 'entering', 'enter', 'exit', 'exiting', 'walking', 'walk', 'running', 'run',
        'standing', 'stand', 'sitting', 'sit', 'seen', 'see', 'detected', 'detect',
        'found', 'find', 'spotted', 'spot', 'with', 'without', 'near', 'around',
        'inside', 'outside', 'somebody', 'anybody', 'they', 'them', 'he', 'she', 'it',
        'about', 'above', 'below', 'under', 'over', 'into', 'out', 'up', 'down'
    }

    words1 = {w.strip('.,!?') for w in text1.split()}
    words2 = {w.strip('.,!?') for w in text2.split()}

    # Strip 's' from the end to naively handle plurals (mask vs masks)
    w1_clean = {w.rstrip('s') for w in words1 - stop_words if len(w) > 2}
    w2_clean = {w.rstrip('s') for w in words2 - stop_words if len(w) > 2}

    # --- Fallback to LLM for synonyms (e.g., 'car' vs 'vehicle') ---
    client = _client()

    prompt = f"""You are a behavior comparator for a surveillance rule engine.

Your job: decide if two rules describe the SAME physical behavior or action and Analyze the MEANING of these two surveillance rules.

A rule conflicts ONLY if the MEANING overlaps. Do not be fooled by different keywords.

Rules:
- Focus ONLY on the ACTION or EVENT being described (e.g. eating, running, entering, fighting).
- IGNORE shared location (cafeteria, hallway, etc.) — location alone is NOT a match.
- IGNORE shared subject (person, someone, employee) — that alone is NOT a match.
- Two rules match only if the BEHAVIOR they describe is the same or semantically equivalent.

STEP 1 - Extract the core action from Rule 1.
  Write only the behavior/action in 1-3 words.
  Strip out completely: location, time, person, negation words.
  Example: "Do not alert if someone is eating in the cafeteria" → action: "eating"
  Example: "Alert me if someone enters the server room after 5 PM" → action: "entering"
  Example: "Do not alert if someone is in the office after 5" → action: "presence"

STEP 2 - Extract the core action from Rule 2 the same way.

STEP 3 - Are the two extracted actions the same behavior or clear synonyms?

SAME behavior examples (same=true):
- "eating" vs "consuming"       → YES (same meaning)
- "drinking coffee" vs "having a drink" → YES (coffee is a drink, subset = same behavior)
- "presence" vs "presence"      → YES (same meaning, even if different location/time)
- "sprinting" vs "rapid movement" → YES
- "fighting" vs "physical confrontation" → YES

DIFFERENT behavior examples (same=false):
- "someone is eating" vs "someone enters the building" → NO (eat ≠ enter)
- "wearing a red shirt" vs "wearing a hat" → NO (shirt ≠ hat)
- "person is smoking" vs "person is eating" → NO (smoke ≠ eat)
- "camera is covered" vs "someone is loitering" → NO (tamper ≠ loiter)
- "smoking" vs "playing" → NO

Rule 1: "{text1}"
Rule 2: "{text2}"

Respond ONLY with this exact JSON and nothing else:
{{"action1": "<core action from rule 1>", "action2": "<core action from rule 2>", "same": true or false}}"""

    for attempt in range(3):
        resp = client.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            options={"temperature": 0.0}
        )

        raw = (resp.get("message") or {}).get("content", "").strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            result = json.loads(raw)
            is_same = bool(result.get("same", False))
            a1 = result.get("action1", "?")
            a2 = result.get("action2", "?")
            reason = (
                f"Same behavior: '{a1}' ≈ '{a2}'"
                if is_same
                else f"Different behaviors: '{a1}' vs '{a2}'"
            )
            
            # Store in cache
            SEMANTIC_CACHE[cache_key] = (is_same, reason)
            return is_same, reason
        except (json.JSONDecodeError, ValueError):
            if attempt == 2:
                return False, "LLM failed"
            continue
    return False, "LLM failed"