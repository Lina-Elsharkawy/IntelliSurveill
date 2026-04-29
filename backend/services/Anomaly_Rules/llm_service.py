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
        # Separate punctuation from word
        stripped = word.strip(".,!?;:")
        punctuation = word[len(stripped):]  # keep trailing punctuation

        if not stripped:
            corrected.append(word)
            continue

        suggestion = spell.correction(stripped)
        # If None (unknown word) or unchanged, keep original
        corrected.append((suggestion if suggestion else stripped) + punctuation)

    return " ".join(corrected)

def parse_rule_with_llm(rule_text: str, rule_type: Literal["trigger", "suppress"]) -> dict:
    """
    Call LLM once to convert natural language rule into structured JSON.
    """
    
    client = ollama.Client(host=OLLAMA_HOST)
    rule_text = correct_spelling(rule_text)

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
    import time
    for attempt in range(3):
        try:
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
        except Exception as e:
            print(f"LLM parse error (attempt {attempt+1}): {e}")
            if attempt == 2:
                # Safe fallback if all attempts fail
                return {
                    "rule_text": rule_text,
                    "event_type": "intrusion",
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

    # overlap = w1_clean & w2_clean
    # if overlap:
    #     return True, f"Same subject detected ({', '.join(overlap)})"

    # --- Fallback to LLM for synonyms (e.g., 'car' vs 'vehicle') ---
    client = ollama.Client(host=OLLAMA_HOST)

    prompt = f"""You are a behavior comparator for a surveillance rule engine.


    Your job: decide if two rules describe the SAME physical behavior or action and Analyze the MEANING of these two surveillance rules.
    
    A  rule conflicts ONLY if the MEANING overlaps. Do not be fooled by different keywords.
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
    - "eating food" vs "consuming a meal" → same (eat/consume overlap)
    - "a vehicle drives in" vs "a car is seen entering" → same (vehicle/car, drive/enter)
    - "someone is sprinting" vs "rapid movement detected" → same (sprint/rapid movement)
    - "eating" vs "consuming"       → YES (same meaning)
    - "drinking coffee" vs "having a drink" → YES (coffee is a drink, subset = same behavior)
    - "presence" vs "presence"      → YES (same meaning, even if different location/time)
    - "sprinting" vs "rapid movement" → YES


    DIFFERENT behavior examples (same=false):
    - "someone is eating" vs "someone enters the building" → DIFFERENT (eat ≠ enter)
    - "wearing a red shirt" vs "wearing a hat" → DIFFERENT (shirt ≠ hat)
    - "person is smoking" vs "person is eating" → DIFFERENT (smoke ≠ eat)
    - "camera is covered" vs "someone is loitering" → DIFFERENT (tamper ≠ loiter)
    - "smoking" vs "playing "         → NO


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
