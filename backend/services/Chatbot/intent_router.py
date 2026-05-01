"""
Structured intent router for the LangGraph surveillance chatbot.

This module intentionally does NOT generate SQL. It maps natural language to a
fixed capability contract and extracts lightweight parameters. SQL generation is
reserved for the dedicated fallback path in langgraph_workflow.py.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from capabilities import SUPPORTED_INTENTS, canonical_intent, required_params, tool_name, tool_type

_WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_WORD_NUMS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_SMALL_TALK_RE = re.compile(
    r"\b(hello|hi|hey|hiya|howdy|how are you|what can you do|help|thanks|thank you|who are you|what is your name|what's your name)\b",
    re.IGNORECASE,
)

_STOP_WORDS = {
    "the", "who", "what", "when", "where", "how", "did", "was", "show", "find", "get",
    "list", "today", "yesterday", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "last", "this", "on", "at", "in", "near", "around", "is", "are",
    "has", "a", "an", "me", "my", "our", "their", "person", "face", "event", "unknown",
    "latest", "recent", "most", "first", "seen", "detected", "timeline", "movement",
}


def extract_date(question: str) -> str | None:
    """Resolve common date expressions to YYYY-MM-DD without using the LLM."""
    q = question.lower()
    today = date.today()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", q)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", q)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    if re.search(r"\btoday\b", q):
        return today.isoformat()
    if re.search(r"\byesterday\b", q):
        return (today - timedelta(days=1)).isoformat()

    num_pat = "|".join(_WORD_NUMS)
    m = re.search(rf"\b(\d+|{num_pat})\s+days?\s+ago\b", q)
    if m:
        n = int(_WORD_NUMS.get(m.group(1), m.group(1)))
        return (today - timedelta(days=n)).isoformat()

    if re.search(r"\blast\s+week\b", q):
        return (today - timedelta(days=7)).isoformat()

    wd_pat = "|".join(re.escape(k) for k in _WEEKDAYS)
    m = re.search(rf"\blast\s+({wd_pat})\b", q)
    if m:
        target = _WEEKDAYS[m.group(1)]
        days_back = (today.weekday() - target) % 7 or 7
        return (today - timedelta(days=days_back)).isoformat()

    m = re.search(rf"\b(?:this|on)\s+({wd_pat})\b", q)
    if m:
        target = _WEEKDAYS[m.group(1)]
        days_back = (today.weekday() - target) % 7
        return (today - timedelta(days=days_back)).isoformat()

    mon_pat = "|".join(_MONTHS)
    m = re.search(rf"\b({mon_pat})\s+(\d{{1,2}})\b", q)
    if m:
        mon, day = _MONTHS[m.group(1)], int(m.group(2))
    else:
        m = re.search(rf"\b(\d{{1,2}})\s+({mon_pat})\b", q)
        if not m:
            return None
        day, mon = int(m.group(1)), _MONTHS[m.group(2)]

    try:
        d = date(today.year, mon, day)
        if d > today:
            d = date(today.year - 1, mon, day)
        return d.isoformat()
    except ValueError:
        return None


def _extract_limit(question: str, default: int = 10, maximum: int = 100) -> int:
    q = question.lower()
    m = re.search(r"\b(?:latest|last|top|show|get|list)\s+(\d{1,3})\b", q)
    if not m:
        m = re.search(r"\blimit\s+(\d{1,3})\b", q)
    if not m:
        return default
    try:
        return max(1, min(maximum, int(m.group(1))))
    except ValueError:
        return default


def _extract_days_back(question: str) -> int | None:
    q = question.lower()
    if any(p in q for p in ["last week", "past week", "last 7 days", "past 7 days"]):
        return 7
    if any(p in q for p in ["last 24 hours", "past 24 hours", "today"]):
        return 1
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", q)
    if m:
        return max(1, min(365, int(m.group(1))))
    return None


def _extract_hour(question: str) -> int | None:
    """Extract an hour from expressions such as 13:00, 1 PM, at 9am."""
    q = question.lower()
    m = re.search(r"\b(?:at|around|by)?\s*(\d{1,2})(?::|\.)(\d{2})\b", q)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", q)
    if m:
        h = int(m.group(1))
        suffix = m.group(2)
        if 1 <= h <= 12:
            if suffix == "pm" and h != 12:
                h += 12
            if suffix == "am" and h == 12:
                h = 0
            return h
    m = re.search(r"\b(?:at|around|near)\s+(\d{1,2})\b", q)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h
    return None


def _extract_event_id(question: str) -> int | None:
    q = question.lower()
    patterns = [
        r"\bunknown\s+face\s+event\s+#?(\d+)\b",
        r"\bevent\s+#?(\d+)\b",
        r"\bunknown\s+#?(\d+)\b",
        r"\bid\s*[:#]?\s*(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _extract_threshold(question: str, default: float) -> float:
    m = re.search(r"\b(?:threshold|similarity)\s*(?:>=|>|=|of|is)?\s*(0?\.\d+|1\.0|1)\b", question.lower())
    if not m:
        return default
    try:
        return max(0.0, min(1.0, float(m.group(1))))
    except ValueError:
        return default


def _extract_name_fallback(question: str) -> str | None:
    # Prefer name after common prepositions/actions.
    m = re.search(
        r"\b(?:for|of|about|near|around|track|timeline for|last seen|first seen|detected)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3})",
        question,
    )
    if m:
        name = m.group(1).strip(" ?.!,\"'")
        if name.lower() not in _STOP_WORDS:
            return name

    parts: list[str] = []
    for word in question.split():
        clean = word.strip("?.,!\"'")
        if clean and clean[0].isupper() and clean.lower() not in _STOP_WORDS and len(clean) > 1:
            parts.append(clean)
        elif parts:
            break
    return " ".join(parts) if parts else None


def _base_params(question: str) -> dict[str, Any]:
    target_date = extract_date(question)
    params: dict[str, Any] = {
        "limit": _extract_limit(question),
    }
    if target_date:
        params["target_date"] = target_date
    days = _extract_days_back(question)
    if days:
        params["days_back"] = days
    event_id = _extract_event_id(question)
    if event_id is not None:
        params["event_id"] = event_id
    hour = _extract_hour(question)
    if hour is not None:
        params["hour"] = hour
    return params


def _deterministic_route(question: str) -> dict[str, Any] | None:
    q = question.lower()
    params = _base_params(question)

    if _SMALL_TALK_RE.search(q):
        return _decision("small_talk", params={}, confidence=1.0)

    if any(p in q for p in [
        "which table has the most records", "tables are empty", "which tables are empty",
        "empty tables", "records in each table", "record count for each table",
        "how many records are in each table",
    ]):
        return _decision("table_record_counts", params={}, confidence=1.0)

    # Deterministic counting routes. These must run before the broader
    # "unknown faces/latest unknown" routes.
    countish = any(p in q for p in ["how many", "count", "number of", "total"])
    if countish and any(p in q for p in ["unknown detection", "unknown detections", "unknown face", "unknown faces", "stranger", "unidentified"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("unknown_detection_count", params=params, confidence=1.0)

    if countish and any(p in q for p in ["known face", "known faces", "known detection", "known detections", "identified face", "identified faces"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("known_face_detection_count", params=params, confidence=1.0)

    if countish and any(p in q for p in ["face", "faces", "detection", "detections", "person", "people"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("face_detection_count", params=params, confidence=0.95)

    event_id = params.get("event_id")
    if event_id is not None:
        if any(p in q for p in ["investigate", "full report", "complete report", "what happened"]):
            return _decision("investigate_unknown_face_event", params={**params, "threshold": _extract_threshold(question, 0.60)}, confidence=1.0)
        if any(p in q for p in ["possible match", "closest match", "who is", "identify", "identity", "known match"]):
            return _decision("possible_identity_match", params={**params, "threshold": _extract_threshold(question, 0.55)}, confidence=1.0)
        if any(p in q for p in ["similar", "appeared before", "seen before", "same person", "come back", "returned"]):
            return _decision("similar_unknown_faces", params={**params, "threshold": _extract_threshold(question, 0.60)}, confidence=1.0)
        if any(p in q for p in ["anomaly", "incident", "near"]):
            return _decision("anomalies_near_unknown_event", params=params, confidence=1.0)
        if "unknown" in q and "event" in q:
            return _decision("unknown_face_event_details", params=params, confidence=1.0)

    if "unknown face event" in q or "unknown face events" in q:
        if "unreviewed" in q or "not reviewed" in q or "not been reviewed" in q:
            params["only_unreviewed"] = True
        elif "reviewed" in q:
            params["only_unreviewed"] = False
        return _decision("latest_unknown_face_events", params=params, confidence=1.0)

    if any(p in q for p in ["latest unknown", "unknown faces", "strangers", "unidentified"]):
        if any(p in q for p in ["repeated", "came back", "more than once", "multiple times", "returned"]):
            return _decision("repeated_unknown_faces", params=params, confidence=0.95)
        return _decision("latest_unknown_face_events", params=params, confidence=0.85)

    if any(p in q for p in ["latest anomalies", "recent anomalies", "show anomalies", "anomaly logs", "incidents"]):
        if any(p in q for p in ["near", "around", "with", "same time"]):
            name = _extract_name_fallback(question)
            if name:
                return _decision("anomalies_near_person", params={**params, "name": name}, confidence=0.85)
        return _decision("latest_anomalies", params=params, confidence=0.9)

    if any(p in q for p in ["daily summary", "security summary", "summary today", "today summary"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("daily_security_summary", params=params, confidence=0.95)

    if any(p in q for p in ["camera activity", "most active camera", "camera summary", "detections by camera"]):
        return _decision("camera_activity_summary", params=params, confidence=0.95)

    return None


_CLASSIFY_PROMPT = """\
You are an intent router for a surveillance investigation chatbot.
Today's date: {today}

Pick exactly ONE supported intent from this list:
{intent_list}

Rules:
- Do NOT write SQL.
- If the question is a trusted surveillance investigation, choose the closest tool intent.
- Use sql_fallback only for generic database exploration/count/list questions that do not need special investigation logic.
- Extract only parameters mentioned or clearly implied.
- Use null for missing values.
- If a specific person is required, extract the person's name exactly as written.
- If an unknown face event id is mentioned, extract event_id as an integer.

Common mapping:
- where/when was NAME last seen/detected -> person_last_seen
- when did NAME first appear/first detected -> person_first_seen
- track/show movement/timeline for NAME -> person_timeline
- who was seen today/yesterday/on DATE -> people_seen_on_date
- how many/count unknown detections/faces at time/date -> unknown_detection_count
- how many/count known faces/detections at time/date -> known_face_detection_count
- latest unknown face events/unreviewed unknowns -> latest_unknown_face_events
- details for unknown event ID -> unknown_face_event_details
- did unknown event ID appear before / similar faces -> similar_unknown_faces
- closest known match / identify unknown event ID -> possible_identity_match
- investigate unknown event ID -> investigate_unknown_face_event
- anomalies near NAME -> anomalies_near_person
- anomalies near unknown event ID -> anomalies_near_unknown_event
- latest anomalies -> latest_anomalies
- daily security summary -> daily_security_summary
- table records/empty tables -> table_record_counts

User question: {question}
Pre-resolved date: {pre_date}
Pre-extracted event_id: {event_id}

Return ONLY valid JSON:
{{
  "intent": "...",
  "confidence": 0.0,
  "params": {{
    "name": null,
    "target_date": null,
    "event_id": null,
    "limit": null,
    "days_back": null,
    "hour": null
  }}
}}
"""


def _llm_route(question: str, pre_params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from model import OllamaLLM
        llm = OllamaLLM()
        prompt = _CLASSIFY_PROMPT.format(
            today=date.today().isoformat(),
            intent_list="\n".join(f"- {k}: {v['description']}" for k, v in SUPPORTED_INTENTS.items()),
            question=question,
            pre_date=pre_params.get("target_date") or "none",
            event_id=pre_params.get("event_id") or "none",
        )
        raw = llm.generate(prompt, temperature=0.0)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group())
        intent = canonical_intent(parsed.get("intent"))
        params = dict(pre_params)
        model_params = parsed.get("params") or {}
        if isinstance(model_params, dict):
            for key, value in model_params.items():
                if value not in (None, "", "null"):
                    params[key] = value
        if not params.get("name"):
            name = parsed.get("name") or _extract_name_fallback(question)
            if name:
                params["name"] = name
        return _decision(intent, params=params, confidence=float(parsed.get("confidence") or 0.5))
    except Exception:
        return None


def _keyword_fallback(question: str, pre_params: dict[str, Any]) -> dict[str, Any]:
    q = question.lower()
    params = dict(pre_params)
    name = _extract_name_fallback(question)
    if name:
        params["name"] = name

    if any(p in q for p in ["first seen", "first detected", "first time", "earliest", "first appeared"]):
        return _decision("person_first_seen", params=params, confidence=0.65)
    if any(p in q for p in ["timeline", "movement", "track", "where did", "route"]):
        return _decision("person_timeline", params=params, confidence=0.65)
    if any(p in q for p in ["last seen", "last detected", "most recent", "latest detection", "where is", "where was"]):
        return _decision("person_last_seen", params=params, confidence=0.65)
    if any(p in q for p in ["who was seen", "who came", "who entered", "who appeared"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("people_seen_on_date", params=params, confidence=0.65)
    return _decision("sql_fallback", params={}, confidence=0.3)


def _decision(intent: str, params: dict[str, Any] | None = None, confidence: float = 0.5) -> dict[str, Any]:
    intent = canonical_intent(intent)
    params = params or {}

    # Normalize param names for existing tools.
    if "person_name" in params and "name" not in params:
        params["name"] = params.pop("person_name")
    if "date" in params and "target_date" not in params:
        params["target_date"] = params.pop("date")

    # Remove null-ish values and irrelevant universal params later in workflow.
    clean = {k: v for k, v in params.items() if v not in (None, "", "null")}
    return {
        "path": tool_type(intent),
        "intent": intent,
        "tool": tool_name(intent),
        "params": clean,
        "confidence": confidence,
        "needs_clarification": False,
        "clarification_question": None,
        "required_params": required_params(intent),
    }


def route(question: str, history: list | None = None) -> dict[str, Any]:
    """Public router entry point used by LangGraph."""
    deterministic = _deterministic_route(question)
    if deterministic:
        return deterministic

    pre_params = _base_params(question)
    routed = _llm_route(question, pre_params) or _keyword_fallback(question, pre_params)

    # If LLM chose a person-intent but forgot the name, try deterministic extraction once.
    if "name" in required_params(routed["intent"]) and not routed.get("params", {}).get("name"):
        name = _extract_name_fallback(question)
        if name:
            routed["params"]["name"] = name

    return routed
