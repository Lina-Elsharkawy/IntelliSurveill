import json
import ollama
from typing import Literal
from config import OLLAMA_HOST, LLM_MODEL
from spellchecker import SpellChecker

ALLOWED_EVENT_TYPES = [
    "intrusion", "loitering", "after_hours", "fall_detected", 
    "fight_detection", "camera_tamper", "sudden_movement", 
    "smoke_fire", "crowd_detection","other"
]

def correct_spelling(text: str) -> str:
    spell = SpellChecker()
    words = text.split()
    corrected = []
    for word in words:
        # Keep punctuation attached words as-is
        clean = word.strip(".,!?")
        suggestion = spell.correction(clean)
        corrected.append(suggestion if suggestion else clean)
    return " ".join(corrected)

def parse_rule_with_llm(rule_text: str, rule_type: Literal["trigger", "suppress"]) -> dict:
    """
    Call LLM once to convert natural language rule into structured JSON.
    """
    
    client = ollama.Client(host=OLLAMA_HOST)

    prompt = f"""You are a rule parser for a surveillance system.
    Convert the following admin rule into a structured JSON object.
    step 0: Check the spelling of the rule text and correct it if needed.
    step 1: {rule_type} is the rule type see it first to help you understand the rule better it will be either trigger or suppress.
    step 2: convert the rule text into a structured JSON object
    ALLOWED event_type values (choose the BEST match):
    - "intrusion"         → unauthorized access, trespassing, entering restricted area
    - "loitering"         → hanging around, standing still, suspicious waiting  
    - "after_hours"       → presence outside business hours, after 5pm, late night
    - "fall_detected"     → person falling down, collapse, trip
    - "fight_detection"   → fighting, physical altercation, violence, brawl, combat
    - "camera_tamper"     → camera blocked, covered, moved, vandalized
    - "sudden_movement"   → running, sprinting, rapid movement
    - "smoke_fire"        → smoke, fire, flames, burning
    - "crowd_detection"   → crowd, gathering, large group, many people
    - "other"             → ONLY use this if NONE of the above match at all     

    If no time range → set time_range to null
    If no location → set location to "All"  
    If no person type → set person_type to null

    EXAMPLES:

    Example 1 - trigger rule:
    Admin rule: "Alert me if somone enters the servr room after 5 PM"
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

    Example 2 - suppress rule:
    Admin rule: "Do not alert if there is a fiight"
    Output:
    {{
      "rule_text": "Do not alert if there is a fight",
      "event_type": "fight_detection",
      "conditions": {{
        "location": "All",
        "time_range": null,
        "person_type": null
      }}
    }}

    Example 3 - suppress rule with location:
    Admin rule: "Ignore crowd allerts in the cafetria between 12 PM and 2 PM"
    Output:
    {{
      "rule_text": "Ignore crowd alerts in the cafeteria between 12 PM and 2 PM",
      "event_type": "crowd_detection",
      "conditions": {{
        "location": "cafeteria",
        "time_range": {{"after": "12:00", "before": "14:00"}},
        "person_type": null
      }}
    }}

    Output ONLY valid JSON. No explanation. No markdown.

    Admin rule: "{rule_text}"
    """

    resp = client.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"temperature": 0.0}
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
        parsed["event_type"] = "intrusion"  # safe fallback

    return parsed

def _llm_same_subject(rule_a: dict, rule_b: dict) -> tuple[bool, str]:
    """
    Since small LLMs (like qwen2.5:3b) can be unreliable for logical comparisons,
    we use a robust hybrid approach:
    1. Extract core nouns/adjectives (by stripping stop words & common verbs) and check for overlap.
    2. If overlap is found, it's a guaranteed conflict (same subject).
    3. If no overlap, fall back to the LLM to catch synonyms.
    """
    text1 = rule_a.get('rule_text', '').lower()
    text2 = rule_b.get('rule_text', '').lower()

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

    overlap = w1_clean & w2_clean
    if overlap:
        return True, f"Same subject detected ({', '.join(overlap)})"

    # --- Fallback to LLM for synonyms (e.g., 'car' vs 'vehicle') ---
    client = ollama.Client(host=OLLAMA_HOST)

    prompt = f"""Analyze the MEANING of these two surveillance rules.
Are they about the SAME core subject, action, or behavior, even if they use different words?

A rule conflicts ONLY if the MEANING overlaps. Do not be fooled by different keywords.

Examples of SAME meaning (same=true):
- "Ignore if a vehicle enters" and "Alert if a car is seen" → same (vehicle/car overlap)
- "Employee is running" and "Someone is sprinting" → same (run/sprint overlap)
- "No weapons allowed" and "Alert if gun detected" → same (weapons/gun)

Examples of DIFFERENT meaning (same=false):
- "wearing a red shirt" and "wearing a hat" → different (shirt vs hat)
- "Someone is smoking" and "Person is eating" → different (smoke vs eat)
- "Alert if umbrella opened" and "Ignore if crying" → different (umbrella vs crying)

Rule 1: "{text1}"
Rule 2: "{text2}"

Answer ONLY JSON: {{"same": true}} or {{"same": false}}"""

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
            reason = result.get("reason", "Same subject (LLM)" if is_same else "Different subjects")
            return is_same, reason
        except (json.JSONDecodeError, ValueError):
            if attempt == 2:
                return False, "LLM failed"
            continue
    return False, "LLM failed"
