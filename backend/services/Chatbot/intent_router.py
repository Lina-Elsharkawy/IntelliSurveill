"""
Intent Router — Surveillance Investigation Chatbot
===================================================

Layer 1 – Deterministic regex   (instant, zero LLM)
Layer 2 – LLM semantic router   (constrained JSON via format param in model.py)
Layer 3 – Keyword fallback      (if LLM is completely down)

CHANGES vs previous version:
  1. _SYSTEM_PROMPT shortened ~50% — 7B follows short sharp prompts better.
     All field-description prose removed (schema in model.py covers it).
  2. Few-shot examples: 8 static → dynamic selection (3-4 most relevant).
     Less noise in the context = better focus on the actual question.
  3. _sanity_check() added after Layer 2: pure Python cost-free override
     for the most common misclassification patterns.
  4. Layer 1 extended with patterns for the 8 new tools:
     anomaly_candidates, anomaly_candidate_review, ollama_jobs,
     scene_window_embeddings, anomaly_rules, edge_devices,
     normal_behavior_models, rule_conflicts.
  5. Layer 3 extended to match Layer 1 new tool coverage.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from capabilities import SUPPORTED_INTENTS, canonical_intent, required_params, tool_name, tool_type

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared extractors (regex only, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_STOP_WORDS = {
    "the", "who", "what", "when", "where", "how", "did", "was", "show", "find",
    "get", "list", "today", "yesterday", "last", "this", "on", "at", "in", "near",
    "around", "is", "are", "has", "a", "an", "me", "my", "our", "their", "person",
    "face", "event", "unknown", "latest", "recent", "most", "first", "seen",
    "detected", "timeline", "movement", "movements", "please", "can", "you",
    "give", "tell", "all", "any", "some", "there", "been", "have", "do", "does",
    "had", "were", "that", "which", "by", "from", "to", "be", "it", "we", "they",
    "he", "she", "check", "look", "search", "query", "time", "date", "day",
    "week", "month", "show", "display", "view", "let", "see",
    "count", "total", "number", "many", "much", "every", "everything",
    "everyone", "everybody", "no", "nobody", "each", "same",
    "known", "people", "employees", "employee", "visitors", "visitor", "staff",
    "registered", "names", "identities", "system", "database", "records",
    "enrolled", "profiles", "identity", "registry",
    "anomaly", "anomalies", "anomalie", "alert", "alerts", "incident",
    "incidents", "logs", "log", "camera", "cameras", "detection", "detections",
    "security", "summary", "report", "activity", "events",
    "location", "locations", "path", "route", "history", "sighting",
    "sightings", "track", "tracking", "follow", "following",
    "building", "entrance", "hall", "corner", "room", "lab", "labs",
    "department", "departments", "administration", "engineering",
    "rule", "rules", "schedule", "schedules", "threshold", "description",
    "table", "tables", "pointing", "belong", "belongs",
    # Schema / entity nouns that are never person names
    "lab", "labs", "laboratory", "laboratories",
    "department", "departments", "departement", "departements",
    "floor", "floors", "zone", "zones", "area", "areas",
    # Pipeline / admin words — must NOT become person names
    "candidate", "candidates", "job", "jobs", "pending", "queued",
    "running", "failed", "resolved", "discarded", "scene", "window",
    "windows", "device", "devices", "model", "models", "conflict", "conflicts",
    "edge", "behavior", "normal", "active", "inactive", "status",
    # Weekday names — must NOT become person names
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def extract_date(question: str) -> str | None:
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

    m = re.search(rf"\b({wd_pat})\b", q)
    if m:
        preceding = q[:m.start()]
        if not re.search(r"\b(?:last|this|on|next)\s*$", preceding):
            target = _WEEKDAYS[m.group(1)]
            days_back = (today.weekday() - target) % 7 or 7
            return (today - timedelta(days=days_back)).isoformat()

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", q)
    if m and not re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", q):
        d_val, m_val = int(m.group(1)), int(m.group(2))
        if 1 <= m_val <= 12 and 1 <= d_val <= 31:
            try:
                result = date(today.year, m_val, d_val)
                if result > today:
                    result = date(today.year - 1, m_val, d_val)
                return result.isoformat()
            except ValueError:
                pass

    mon_pat = "|".join(_MONTHS)
    m = re.search(rf"\b(\d{{1,2}})\s+({mon_pat})", q)
    if m:
        day, mon = int(m.group(1)), _MONTHS[m.group(2)]
    else:
        m = re.search(rf"\b({mon_pat})\s+(\d{{1,2}})\b", q)
        if m:
            mon, day = _MONTHS[m.group(1)], int(m.group(2))
        else:
            m = re.search(rf"\b({mon_pat})(\d{{1,2}})\b", q)
            if m:
                mon, day = _MONTHS[m.group(1)], int(m.group(2))
            else:
                m = re.search(rf"\b(\d{{1,2}})({mon_pat})\b", q)
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


def _extract_event_id(question: str) -> int | None:
    patterns = [
        r"\bunknown\s+(?:face\s+)?event\s+#?(\d+)\b",
        r"\bevent\s+(?:id\s*[:#]?\s*)?#?(\d+)\b",
        r"\bid\s*[:#]?\s*(\d+)\b",
        r"#(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, question, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _extract_limit(question: str, default: int = 10) -> int:
    m = re.search(r"\b(?:latest|last|top|show|get|list)\s+(\d{1,3})(?!\s*(?:am|pm|:))\b", question.lower())
    if not m:
        m = re.search(r"\blimit\s+(\d{1,3})\b", question.lower())
    if not m:
        return default
    try:
        return max(1, min(100, int(m.group(1))))
    except ValueError:
        return default


def _extract_days_back(question: str) -> int | None:
    q = question.lower()
    if any(p in q for p in ["last week", "past week", "last 7 days"]):
        return 7
    if re.search(r"\bthis\s+month\b", q):
        return 30
    if re.search(r"\bthis\s+week\b", q):
        return 7
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", q)
    if m:
        return max(1, min(365, int(m.group(1))))
    return None


def _extract_hour(question: str) -> int | None:
    q = question.lower()
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", q)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return h
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", q)
    if m:
        h, suffix = int(m.group(1)), m.group(2)
        if 1 <= h <= 12:
            if suffix == "pm" and h != 12:
                h += 12
            if suffix == "am" and h == 12:
                h = 0
            return h
    return None


def _extract_name(question: str) -> str | None:
    """
    Extract a person name from natural language.
    Handles title-case and lowercase — users rarely capitalize names in chat.
    """
    kw = (
        r"for|of|about|near|around|track|follow|locate|find|"
        r"where is|where was|last seen|first seen|first detected|last detected|"
        r"timeline for|movement of|path of|sighting of|"
        r"when was|when did|spotted|detected|seen|appeared|entered"
    )
    m = re.search(
        rf"\b(?:{kw})\s+([a-zA-Z][a-z'-]+(?:\s+[a-zA-Z][a-z'-]+)?)",
        question, re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip("?.,!\"' ")
        words = raw.split()
        name_parts = []
        for w in words:
            clean = re.sub(r"['']\.?s$", "", w, flags=re.IGNORECASE)
            if clean.lower() in _STOP_WORDS:
                break
            name_parts.append(clean)
        if name_parts:
            candidate = " ".join(name_parts)
            if candidate.lower() not in _STOP_WORDS and len(candidate) > 1:
                return candidate.title()

    m = re.search(r"\b([A-Za-z][a-zA-Z'-]+(?:\s+[A-Za-z][a-zA-Z'-]+){0,2})['']\.?s\b",
                  question, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        name_words = name.split()
        clean_parts = [w for w in name_words if w.lower() not in _STOP_WORDS]
        if clean_parts:
            name = " ".join(clean_parts)
            if name.lower() not in _STOP_WORDS:
                return name.title()

    m = re.search(
        r"\b(?:find|locate|track|follow|search for|look for|check on|"
        r"show|get|fetch|pull|display)\s+([a-z][a-z'-]+(?:\s+[a-z][a-z'-]+)?)\b",
        question.lower(),
    )
    if m:
        raw = m.group(1).strip()
        words = raw.split()
        name_parts = []
        for w in words:
            clean = re.sub(r"['']\.?s$", "", w)
            if clean in _STOP_WORDS:
                break
            name_parts.append(clean)
        if name_parts:
            candidate = " ".join(name_parts)
            if len(candidate) > 1:
                return candidate.title()

    m = re.search(
        r"\b([a-z][a-z'-]+(?:\s+[a-z][a-z'-]+)?)\s+(?:was|is|has been|were|have been)\s+"
        r"(?:seen|detected|spotted|found|identified|appeared|entered|last seen|first seen)\b",
        question.lower(),
    )
    if m:
        raw = m.group(1).strip()
        words = raw.split()
        name_parts = [w for w in words if w not in _STOP_WORDS]
        if name_parts:
            candidate = " ".join(name_parts)
            if len(candidate) > 1:
                return candidate.title()

    parts: list[str] = []
    for word in question.split():
        clean = word.strip("?.,!\"'")
        clean = re.sub(r"['']\.?s$", "", clean, flags=re.IGNORECASE)
        if clean and clean[0].isupper() and clean.lower() not in _STOP_WORDS and len(clean) > 1:
            parts.append(clean)
        elif parts:
            break
    if parts:
        return " ".join(parts)

    # Fallback for very short queries (e.g., "maged", "find maged", "maged timeline")
    # If the query is 3 words or fewer, any non-stopword is likely the name.
    words = [w.strip("?.,!\"'") for w in question.split()]
    valid_words = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 1 and re.match(r"^[a-zA-Z'-]+$", w)]
    if valid_words and len(words) <= 3:
        return " ".join(valid_words).title()

    return None


def _base_params(question: str) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": _extract_limit(question)}
    if td := extract_date(question):
        params["target_date"] = td
    if db := _extract_days_back(question):
        params["days_back"] = db
    if (eid := _extract_event_id(question)) is not None:
        params["event_id"] = eid
    if (hr := _extract_hour(question)) is not None:
        params["hour"] = hr
    return params


def _decision(intent: str, params: dict[str, Any] | None = None, confidence: float = 0.9) -> dict[str, Any]:
    intent = canonical_intent(intent)
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "", "null")}
    if "person_name" in clean and "name" not in clean:
        clean["name"] = clean.pop("person_name")
    if "date" in clean and "target_date" not in clean:
        clean["target_date"] = clean.pop("date")
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


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Deterministic (instant, zero LLM)
# ─────────────────────────────────────────────────────────────────────────────

_SMALL_TALK_RE = re.compile(
    r"^\s*(hello|hi\b|hey\b|hiya|howdy|how are you|what can you do|"
    r"help\s*$|thanks|thank you|who are you|what is your name|"
    r"what'?s your name|good morning|good afternoon|good evening)\b",
    re.IGNORECASE,
)


def _layer1_deterministic(question: str) -> dict[str, Any] | None:
    q = question.lower().strip()
    params = _base_params(question)

    # ── Small talk ────────────────────────────────────────────────────────────
    if _SMALL_TALK_RE.search(q):
        return _decision("small_talk", confidence=1.0)

    # ── Event ID present → route by action verb ───────────────────────────────
    eid = params.get("event_id")
    if eid is not None:
        if any(p in q for p in ["investigate", "full report", "complete report", "full investigation"]):
            return _decision("investigate_unknown_face_event", params={**params, "threshold": 0.60}, confidence=1.0)
        if any(p in q for p in ["who is", "identify", "possible match", "known match", "closest known", "who could", "identity"]):
            return _decision("possible_identity_match", params={**params, "threshold": 0.55}, confidence=1.0)
        if any(p in q for p in ["similar", "appeared before", "seen before", "came back", "has this person", "been seen before"]):
            return _decision("similar_unknown_faces", params={**params, "threshold": 0.60}, confidence=1.0)
        if any(p in q for p in ["anomaly", "anomalies", "incident", "alert near", "incident near"]):
            return _decision("anomalies_near_unknown_event", params=params, confidence=1.0)
        if any(p in q for p in ["details", "detail", "info about event", "tell me about event", "what is event", "show event"]):
            return _decision("unknown_face_event_details", params=params, confidence=1.0)

    # ── NEW: Anomaly candidates ───────────────────────────────────────────────
    if any(p in q for p in [
        "anomaly candidate", "anomaly candidates", "pending candidate", "pending candidates",
        "show candidates", "list candidates", "sent to llm", "candidate status",
        "resolved candidate", "discarded candidate", "failed candidate",
    ]):
        status = None
        if "pending" in q:
            status = "pending"
        elif "sent to llm" in q:
            status = "sent_to_llm"
        elif "resolved" in q:
            status = "resolved"
        elif "discarded" in q:
            status = "discarded"
        elif "failed" in q:
            status = "failed"
        p2 = dict(params)
        if status:
            p2["status"] = status
        return _decision("anomaly_candidates", params=p2, confidence=1.0)

    # ── NEW: Anomaly candidate review ─────────────────────────────────────────
    if any(p in q for p in [
        "candidate review", "review decision", "confirmed anomal", "dismissed anomal",
        "admin decided", "admin decision", "reviewer decision", "uncertain anomal",
        "human review", "reviewed candidate",
    ]):
        decision_val = None
        if "confirmed" in q:
            decision_val = "confirmed"
        elif "dismissed" in q:
            decision_val = "dismissed"
        elif "uncertain" in q:
            decision_val = "uncertain"
        p2 = dict(params)
        if decision_val:
            p2["status"] = decision_val
        return _decision("anomaly_candidate_review", params=p2, confidence=1.0)

    # ── NEW: Ollama jobs ──────────────────────────────────────────────────────
    if any(p in q for p in [
        "ollama job", "ollama jobs", "llm job", "llm jobs", "job queue", "job status",
        "queued job", "running job", "failed job", "succeeded job",
        "background job", "background jobs", "any failed jobs", "jobs running",
    ]):
        status = None
        if "queued" in q:
            status = "queued"
        elif "running" in q:
            status = "running"
        elif "failed" in q:
            status = "failed"
        elif "succeeded" in q or "success" in q:
            status = "succeeded"
        p2 = dict(params)
        if status:
            p2["status"] = status
        return _decision("ollama_jobs", params=p2, confidence=1.0)

    # ── NEW: Scene window embeddings ──────────────────────────────────────────
    if any(p in q for p in [
        "scene window", "scene windows", "flagged window", "flagged windows",
        "anomalous window", "anomalous scene", "scene anomal",
        "l2 score", "mse score", "cos flag", "scene embedding",
        "which windows were flagged", "flagged video",
    ]):
        p2 = dict(params)
        if any(p in q for p in ["flagged", "anomalous", "is_anomalous"]):
            p2["status"] = "anomalous"
        return _decision("scene_window_embeddings", params=p2, confidence=1.0)

    # ── NEW: Anomaly rules ────────────────────────────────────────────────────
    _RULES_TRIGGERS = [
        "anomaly rule", "anomaly rules", "trigger rule", "suppress rule",
        "intrusion rule", "loitering rule", "fight rule", "rule list",
        "list rules", "show rules", "active rules", "monitoring rule",
        "what rules", "which rules", "learned rule", "admin rule",
        "how many rules", "how many active", "how many inactive",
        "count rules", "inactive rules",
        # Additional flexible patterns
        "what are rules", "what are the rules", "are rules",
        "rules is active", "rules is inactive", "rules are active", "rules are inactive",
        "rules with status", "rules status",
    ]
    if any(p in q for p in _RULES_TRIGGERS) or re.search(r'\brules?\b.{0,20}\b(active|inactive|disabled)\b', q):
        p2 = dict(params)
        # rule_type filter
        if "trigger" in q:
            p2["rule_type"] = "trigger"
        elif "suppress" in q:
            p2["rule_type"] = "suppress"
        # is_active filter — check for inactive first to avoid partial match with "active"
        if "inactive" in q or "not active" in q or "disabled" in q:
            p2["is_active"] = False
        elif re.search(r'\bactive\b', q) and "inactive" not in q:
            p2["is_active"] = True
        # specific rule ID: "rule 32", "rule #32", "anomaly rule 32"
        m_rid = re.search(r"\brule\s+#?(\d+)\b", q)
        if m_rid:
            p2["rule_id"] = int(m_rid.group(1))
        return _decision("anomaly_rules", params=p2, confidence=1.0)

    # ── NEW: Edge devices ─────────────────────────────────────────────────────
    if any(p in q for p in [
        "edge device", "edge devices", "registered device", "registered devices",
        "jetson", "rockpi", "hardware device", "processing device",
        "list devices", "show devices", "which devices",
    ]):
        return _decision("edge_devices", params=params, confidence=1.0)

    # ── NEW: Normal behavior models ───────────────────────────────────────────
    if any(p in q for p in [
        "behavior model", "behavior models", "normal behavior", "normal model",
        "active model", "active models", "videomae model", "teacher model",
        "student model", "list models", "show models", "which models",
    ]):
        return _decision("normal_behavior_models", params=params, confidence=1.0)

    # ── NEW: Rule conflicts ───────────────────────────────────────────────────
    if any(p in q for p in [
        "rule conflict", "rule conflicts", "conflicting rule", "conflicting rules",
        "contradicting rule", "pending conflict", "conflict status",
    ]):
        return _decision("rule_conflicts", params=params, confidence=1.0)

    # ── Schema exploration: list labs, departments, cameras, schedules, etc. ──
    # These are simple "show me the contents of table X" queries.
    # Route them directly to sql_fallback so the LLM generates a SELECT.
    _SCHEMA_EXPLORE_TRIGGERS = [
        # labs
        "list lab", "list the lab", "list to me the lab", "show lab", "show the lab",
        "what labs", "which labs", "labs we have", "our labs",
        # departments (including common misspelling)
        "list department", "list the department", "list to me the department",
        "show department", "show the department",
        "what department", "which department", "departments we have", "our department",
        "list departement", "list the departement", "list to me the departement",
        "show departement", "departements we have", "our departement",
        # cameras
        "list camera", "list the camera", "list to me the camera",
        "show camera", "show the camera", "what cameras", "which cameras", "our cameras",
        # schedules
        "list schedule", "show schedule", "what schedule", "our schedule",
        # employees  (generic listing — no person name given)
        "list to me the employee", "list to me the employees",
        "show to me the employee", "show to me the employees",
    ]
    if any(p in q for p in _SCHEMA_EXPLORE_TRIGGERS):
        return _decision("sql_fallback", params={}, confidence=0.9)


    _KNOWN_PEOPLE_TRIGGERS = [
        "list known", "show known", "names of known", "who are the known",
        "list all known", "show all known",
        "list employees", "show employees", "who are the employees",
        "all employees", "show all employees", "list all employees",
        "show me the employees", "show me employees",
        "show me the visitors", "show me visitors",
        "list visitors", "show visitors", "who are the visitors",
        "all visitors", "show all visitors", "list all visitors",
        "registered people", "known identities", "known people",
        "people in the system", "people in the database", "people registered",
        "who do we know", "who is registered", "names in the system",
        "who are registered",
        "show me everyone", "show everyone", "list everyone",
        "everyone registered", "everyone in the system", "everyone in the database",
        "everybody registered", "everybody in the system",
        "list the identities", "list identities", "show identities",
        "show me the identities", "list to me the identities",
        "enrolled profiles", "show enrolled", "list enrolled",
    ]
    if any(p in q for p in _KNOWN_PEOPLE_TRIGGERS):
        ptype = None
        if any(p in q for p in ["employee", "employees", "staff"]):
            ptype = "employee"
        elif any(p in q for p in ["visitor", "visitors"]):
            ptype = "visitor"
        p2 = dict(params)
        if ptype:
            p2["person_type"] = ptype
        return _decision("all_known_people", params=p2, confidence=1.0)

    # ── Table / record counts ─────────────────────────────────────────────────
    if any(p in q for p in [
        "which table has the most", "most records", "largest table",
        "tables are empty", "empty tables", "records in each table",
        "record count", "how many rows in each", "table sizes", "records per table",
        "how many tables", "how many records", "how many rows", "how any tables",
        "how many cameras", "how many employees", "how many visitors",
        "how many entry logs", "how many anomalies", "how many events",
        "how many departments", "how many labs", "how many rules",
        "how many schedules", "how many people", "how many faces",
        "how any unknown face events", "how any known face events", "how any events",
        "count departments", "count labs", "count rules", "count cameras",
        "count employees", "count visitors", "count tables",
        "count the number of", "number of labs", "number of cameras",
        "number of employees", "number of departments", "number of rules",
        "number of visitors", "number of schedules",
    ]):
        return _decision("table_record_counts", params={}, confidence=1.0)

    # ── Daily security summary ────────────────────────────────────────────────
    if any(p in q for p in [
        "daily summary", "security summary", "daily security", "daily report",
        "brief me", "update me", "situation report", "what happened today",
        "today's report", "today report", "status report",
        "what happened", "what happen",
        "who were seen", "who came in last",
        "detections in last", "detections last",
        "total detections last", "total known last", "total unknown last",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("daily_security_summary", params=params, confidence=1.0)

    # ── Camera activity summary ───────────────────────────────────────────────
    if any(p in q for p in [
        "camera activity", "camera summary", "which camera detected", "which camera saw",
        "camera stats", "camera statistics", "busiest camera", "most active camera",
        "detections per camera", "camera report",
    ]):
        return _decision("camera_activity_summary", params=params, confidence=1.0)

    # ── Latest anomalies ──────────────────────────────────────────────────────
    if any(p in q for p in [
        "latest anomalies", "recent anomalies", "show anomalies", "list anomalies",
        "any anomalies", "anomalies today", "recent incidents", "latest incidents",
        "recent alerts", "latest alerts",
    ]):
        return _decision("latest_anomalies", params=params, confidence=1.0)

    # ── Repeated unknown faces ────────────────────────────────────────────────
    if any(p in q for p in [
        "repeated unknown", "came back", "returned visitor", "seen more than once",
        "multiple times", "repeat visitor", "recurring unknown", "unknown returned",
    ]):
        return _decision("repeated_unknown_faces", params=params, confidence=1.0)

    # ── Latest unknown face events (listing) ──────────────────────────────────
    if any(p in q for p in [
        "latest unknown", "recent unknown", "show unknown faces", "list unknown faces",
        "unknown face events", "strangers today", "unidentified people",
        "unknown people", "unreviewed unknown",
    ]):
        p2 = dict(params)
        if "unreviewed" in q:
            p2["only_unreviewed"] = True
        return _decision("latest_unknown_face_events", params=p2, confidence=1.0)

    # ── Unknown detection count ───────────────────────────────────────────────
    if any(p in q for p in [
        "how many unknown", "count unknown", "number of unknown",
        "how many strangers", "how many unidentified", "unknown detection count",
        "count of unknown", "total unknown", "total strangers",
        "count the strangers", "count strangers",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("unknown_detection_count", params=params, confidence=1.0)

    # ── Known face detection count ────────────────────────────────────────────
    if any(p in q for p in [
        "how many known", "count known", "number of known",
        "how many identified", "known detection count", "count of known",
        "how many recognized", "known faces detected",
        "total known face", "total known detection", "total identified",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("known_face_detection_count", params=params, confidence=1.0)

    # ── Total face / detection count ──────────────────────────────────────────
    if any(p in q for p in [
        "how many people were detected", "total detections", "how many detections",
        "total faces", "how many faces", "detection count", "count detections",
        "how many people detected", "face detection count",
        "total face detections", "total face detection",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("face_detection_count", params=params, confidence=1.0)

    # ── People seen on date ───────────────────────────────────────────────────
    if any(p in q for p in [
        "who was seen", "who was detected", "who came in", "who entered",
        "who appeared", "who visited", "who was present", "people seen",
        "people detected", "people present", "which people",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("people_seen_on_date", params=params, confidence=1.0)

    # ── Person-specific intents (require name) ────────────────────────────────
    name = _extract_name(question)

    if name:
        params["name"] = name
        if any(p in q for p in ["anomaly near", "anomalies near", "incident near", "alert near",
                                 "anomaly when", "incident when", "alert when"]):
            return _decision("anomalies_near_person", params=params, confidence=1.0)
        if any(p in q for p in ["first seen", "first detected", "first time", "earliest",
                                 "first appeared", "first entry", "first time seen",
                                 "when first", "earliest detection",
                                 "first inserted", "first added", "first registered",
                                 "first appear", "first record", "initially registered"]):
            return _decision("person_first_seen", params=params, confidence=1.0)
        if any(p in q for p in ["timeline", "movement", "movements", "route", "path", "track",
                                 "where did", "which cameras", "cameras visited",
                                 "all detections for"]):
            params.setdefault("target_date", date.today().isoformat())
            return _decision("person_timeline", params=params, confidence=1.0)
        if any(p in q for p in ["last seen", "last detected", "most recent", "recently seen",
                                 "where is", "where was", "locate", "find", "spotted",
                                 "current location", "latest detection", "last sighting",
                                 "last location", "catch", "caught", "capture", "captured"]):
            return _decision("person_last_seen", params=params, confidence=1.0)

        # Bare name query — default to last seen
        return _decision("person_last_seen", params=params, confidence=0.85)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — LLM semantic classifier
# ─────────────────────────────────────────────────────────────────────────────

# Shorter, sharper system prompt for 7B.
# No prose rules — the JSON schema in model.py _INTENT_SCHEMA covers field types.
# Few-shot examples demonstrate the pattern; the model doesn't need instructions.
_SYSTEM_PROMPT = """\
You are a JSON intent classifier for a surveillance security system.
Today: {today}

OUTPUT: a single JSON object only. No explanation. No markdown.
Use null (not "null", not "") for absent fields. event_id must be integer.

INTENTS:
person_last_seen, person_first_seen, person_timeline,
people_seen_on_date, unknown_detection_count, known_face_detection_count,
face_detection_count, latest_unknown_face_events, unknown_face_event_details,
repeated_unknown_faces, similar_unknown_faces, possible_identity_match,
investigate_unknown_face_event, latest_anomalies, anomalies_near_person,
anomalies_near_unknown_event, camera_activity_summary, daily_security_summary,
table_record_counts, all_known_people,
anomaly_candidates, anomaly_candidate_review, ollama_jobs,
scene_window_embeddings, anomaly_rules, edge_devices,
normal_behavior_models, rule_conflicts,
sql_fallback, small_talk

RULES:
- person_* needs a name
- *_unknown_face_event* / similar_unknown_faces / possible_identity_match needs event_id
- anomalies_near_person needs a name
- people_seen_on_date = who was seen on a date (no single name)
- anomaly_candidates = pipeline candidates (pending/sent_to_llm/resolved/discarded)
- ollama_jobs = background job queue (queued/running/failed/succeeded)
- anomaly_rules = trigger/suppress rules for intrusion/loitering/fight
- sql_fallback only if truly nothing else fits"""

# Full pool of few-shot examples — dynamically trimmed per question
_ALL_FEW_SHOT = [
    # person intents
    ("find maged",
     '{"intent":"person_last_seen","name":"Maged","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("show ahmed movements yesterday",
     '{"intent":"person_timeline","name":"Ahmed","target_date":"{yesterday}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("when was lina first detected",
     '{"intent":"person_first_seen","name":"Lina","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("when was ahmed first inserted in the system",
     '{"intent":"person_first_seen","name":"Ahmed","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    # group / count
    ("who was seen today",
     '{"intent":"people_seen_on_date","name":null,"target_date":"{today}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("how many unknown faces today",
     '{"intent":"unknown_detection_count","name":null,"target_date":"{today}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    # event-based
    ("investigate unknown face event 274",
     '{"intent":"investigate_unknown_face_event","name":null,"target_date":null,"event_id":274,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("who could event 88 be",
     '{"intent":"possible_identity_match","name":null,"target_date":null,"event_id":88,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    # anomaly / registry
    ("any anomalies near ahmed",
     '{"intent":"anomalies_near_person","name":"Ahmed","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("who are the known people",
     '{"intent":"all_known_people","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    # NEW tools
    ("show pending anomaly candidates",
     '{"intent":"anomaly_candidates","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":"pending"}'),
    ("are there any failed ollama jobs",
     '{"intent":"ollama_jobs","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":"failed"}'),
    ("show active anomaly rules",
     '{"intent":"anomaly_rules","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("which scene windows were flagged",
     '{"intent":"scene_window_embeddings","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":"anomalous"}'),
    ("show edge devices",
     '{"intent":"edge_devices","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("list behavior models",
     '{"intent":"normal_behavior_models","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
    ("any rule conflicts",
     '{"intent":"rule_conflicts","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null,"status":null}'),
]

# Intent → example indices — for dynamic selection
_INTENT_EXAMPLE_IDX = {
    "person": [0, 1, 2],
    "group_count": [3, 4],
    "event": [5, 6],
    "anomaly_person": [7],
    "registry": [8],
    "candidate": [9],
    "job": [10],
    "rule": [11],
    "scene": [12],
    "device": [13],
    "model": [14],
    "conflict": [15],
}


def _pick_few_shot(question: str, n: int = 4) -> list[tuple[str, str]]:
    """
    Dynamically select the most relevant few-shot examples for this question.
    Always include 1-2 generic examples + topic-specific ones.
    Keeps the prompt well under 1500 tokens regardless of the question.
    """
    q = question.lower()
    selected: list[int] = []

    # Topic-specific selection
    if any(p in q for p in ["candidate", "pending candidate"]):
        selected += _INTENT_EXAMPLE_IDX["candidate"]
    if any(p in q for p in ["ollama job", "llm job", "job queue", "failed job"]):
        selected += _INTENT_EXAMPLE_IDX["job"]
    if any(p in q for p in ["anomaly rule", "trigger rule", "suppress rule"]):
        selected += _INTENT_EXAMPLE_IDX["rule"]
    if any(p in q for p in ["scene window", "flagged window", "anomalous window"]):
        selected += _INTENT_EXAMPLE_IDX["scene"]
    if any(p in q for p in ["edge device", "jetson", "hardware device"]):
        selected += _INTENT_EXAMPLE_IDX["device"]
    if any(p in q for p in ["behavior model", "normal model", "videomae"]):
        selected += _INTENT_EXAMPLE_IDX["model"]
    if any(p in q for p in ["rule conflict", "conflicting rule"]):
        selected += _INTENT_EXAMPLE_IDX["conflict"]
    if re.search(r"\bevent\s*#?\d+\b|#\d+", q):
        selected += _INTENT_EXAMPLE_IDX["event"]
    if any(p in q for p in ["anomal", "incident", "alert"]) and _extract_name(question):
        selected += _INTENT_EXAMPLE_IDX["anomaly_person"]

    # Always add a person example if name is present
    if _extract_name(question) and 0 not in selected:
        selected.append(0)

    # Fill remaining slots with group/count examples
    for idx in _INTENT_EXAMPLE_IDX["group_count"]:
        if len(selected) >= n:
            break
        if idx not in selected:
            selected.append(idx)

    # Deduplicate, cap at n
    seen: set[int] = set()
    result: list[int] = []
    for i in selected:
        if i not in seen:
            seen.add(i)
            result.append(i)
        if len(result) >= n:
            break

    return [_ALL_FEW_SHOT[i] for i in result]


def _build_few_shot_user_message(question: str, pre_date: str | None, event_id: int | None) -> str:
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    examples = _pick_few_shot(question, n=4)

    lines = ["EXAMPLES:"]
    for q_ex, out in examples:
        out_filled = out.replace("{today}", today_str).replace("{yesterday}", yesterday_str)
        lines.append(f'Input: "{q_ex}"')
        lines.append(f"Output: {out_filled}")
        lines.append("")

    lines.append("Classify:")
    lines.append(f'Input: "{question}"')
    if pre_date:
        lines.append(f"(pre-resolved date: {pre_date})")
    if event_id is not None:
        lines.append(f"(pre-extracted event_id: {event_id})")
    lines.append("Output:")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Sanity check — pure Python, cost-free override after Layer 2
# Catches the most common LLM misclassification patterns
# ─────────────────────────────────────────────────────────────────────────────

def _sanity_check(intent: str, params: dict[str, Any], question: str) -> str:
    """
    Override obviously wrong classifications based on extracted params.
    Returns the corrected intent name.
    """
    q = question.lower()

    # event_id present but intent doesn't use it → fix
    if params.get("event_id") is not None:
        if intent in {"person_last_seen", "person_timeline", "people_seen_on_date",
                      "latest_unknown_face_events", "latest_anomalies"}:
            if any(p in q for p in ["investigate", "full"]):
                return "investigate_unknown_face_event"
            if any(p in q for p in ["similar", "came back"]):
                return "similar_unknown_faces"
            if any(p in q for p in ["who", "identify", "identity", "match"]):
                return "possible_identity_match"
            return "unknown_face_event_details"

    # name present but intent is a count — probably wrong
    if params.get("name") and intent in {
        "unknown_detection_count", "face_detection_count",
        "latest_unknown_face_events", "table_record_counts",
    }:
        return "person_last_seen"

    # Fix 3 (post-LLM override): "first" in question but intent is last_seen
    if any(p in q for p in ["first", "earliest", "initial", "initially", "registered"]) and intent == "person_last_seen":
        return "person_first_seen"

    # "how many" in question but intent is a listing
    if re.search(r"\bhow\s+many\b|\bcount\b|\btotal\b", q):
        if intent in {"latest_unknown_face_events", "latest_anomalies", "all_known_people"}:
            if "unknown" in q or "stranger" in q:
                return "unknown_detection_count"
            if "known" in q or "identified" in q:
                return "known_face_detection_count"
            if "people" in q or "detection" in q or "face" in q:
                return "face_detection_count"

    # "pending" / "candidate" in question but intent is anomaly_candidate_review
    if any(p in q for p in ["pending", "sent to llm"]) and intent == "anomaly_candidate_review":
        return "anomaly_candidates"

    # "failed" / "queued" / "running" in question but intent is wrong
    if any(p in q for p in ["ollama job", "llm job", "job queue", "failed job",
                             "queued job", "running job"]):
        if intent != "ollama_jobs":
            return "ollama_jobs"

    return intent


# ─────────────────────────────────────────────────────────────────────────────
# Intent cache
# ─────────────────────────────────────────────────────────────────────────────

_INTENT_CACHE: dict[str, str] = {}


def _normalize_question(question: str) -> str:
    """Normalize names, dates, IDs so similar questions share a cache key."""
    q = question.lower()
    name = _extract_name(question)
    if name:
        q = q.replace(name.lower(), "NAME")
    q = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "DATE", q)
    q = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?\b", "DATE", q)
    q = re.sub(r"\btoday\b|\byesterday\b|\blast week\b|\bthis week\b", "DATE", q)
    q = re.sub(r"\bevent\s+#?\d+\b", "EVENT_ID", q)
    q = re.sub(r"\bid\s*[:#]?\s*\d+\b", "ID", q)
    q = re.sub(r"#\d+\b", "ID", q)
    return q.strip()


def _layer2_llm(question: str, pre_params: dict[str, Any]) -> dict[str, Any] | None:
    """
    LLM semantic classification.
    Uses constrained JSON schema (model.py) so output is always valid.
    Merges with regex-extracted params, then runs sanity check.
    """
    try:
        from model import OllamaLLM
        llm = OllamaLLM()

        system = _SYSTEM_PROMPT.format(today=date.today().isoformat())
        user_msg = _build_few_shot_user_message(
            question,
            pre_params.get("target_date"),
            pre_params.get("event_id"),
        )

        norm_q = _normalize_question(question)
        if norm_q in _INTENT_CACHE:
            raw_json = _INTENT_CACHE[norm_q]
        else:
            raw = llm.classify(system, user_msg, temperature=0.0)
            # Clean any accidental markdown fences (shouldn't happen with constrained decoding)
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            raw_json = m.group()
            if "sql_fallback" not in raw_json:
                _INTENT_CACHE[norm_q] = raw_json

        parsed = json.loads(raw_json)
        raw_intent = parsed.get("intent", "sql_fallback")

        # Merge: regex-extracted params win for dates and event IDs (more reliable)
        params = dict(pre_params)
        for key in ("name", "target_date", "event_id", "limit", "days_back",
                    "hour", "only_unreviewed", "person_type", "status"):
            val = parsed.get(key)
            if val is None or val == "null" or val == "":
                continue
            if key in ("target_date", "event_id") and key in params:
                continue  # regex wins
            params[key] = val

        # Last resort: if intent needs name but LLM missed it, try regex
        if "name" in required_params(raw_intent) and not params.get("name"):
            fallback_name = _extract_name(question)
            if fallback_name:
                params["name"] = fallback_name

        # Sanity check before committing
        corrected_intent = _sanity_check(raw_intent, params, question)
        final_intent = canonical_intent(corrected_intent)

        return _decision(final_intent, params=params, confidence=0.88)

    except Exception as exc:
        logger.warning("Layer 2 LLM classification failed: %s", exc, exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Keyword fallback (only if Ollama is completely down)
# ─────────────────────────────────────────────────────────────────────────────

def _layer3_keyword_fallback(question: str, pre_params: dict[str, Any]) -> dict[str, Any]:
    q = question.lower()
    params = dict(pre_params)
    name = _extract_name(question)
    if not name:
        m = re.search(
            r"\b(?:near|about|for|of)\s+([a-zA-Z][a-z]+(?:\s+[a-zA-Z][a-z]+){0,2})\b",
            question, re.IGNORECASE
        )
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in _STOP_WORDS and len(candidate) > 1:
                name = candidate.title()
    if name:
        params["name"] = name

    # New tools first (more specific)
    if any(p in q for p in ["anomaly candidate", "pending candidate", "sent to llm"]):
        return _decision("anomaly_candidates", params=params, confidence=0.70)
    if any(p in q for p in ["candidate review", "confirmed anomal", "dismissed anomal"]):
        return _decision("anomaly_candidate_review", params=params, confidence=0.70)
    if any(p in q for p in ["ollama job", "llm job", "job queue", "failed job"]):
        return _decision("ollama_jobs", params=params, confidence=0.70)
    if any(p in q for p in ["scene window", "flagged window", "anomalous window"]):
        return _decision("scene_window_embeddings", params=params, confidence=0.70)
    if any(p in q for p in ["anomaly rule", "trigger rule", "suppress rule",
                             "list rules", "show rules", "what rules", "what are rules",
                             "inactive rules", "active rules", "rules with status"]) \
            or re.search(r'\brules?\b.{0,20}\b(active|inactive|disabled)\b', q):
        p2 = dict(params)
        if "inactive" in q or "not active" in q or "disabled" in q:
            p2["is_active"] = False
        elif re.search(r'\bactive\b', q) and "inactive" not in q:
            p2["is_active"] = True
        return _decision("anomaly_rules", params=p2, confidence=0.70)
    if any(p in q for p in ["edge device", "jetson", "hardware device"]):
        return _decision("edge_devices", params=params, confidence=0.70)
    if any(p in q for p in ["behavior model", "normal model"]):
        return _decision("normal_behavior_models", params=params, confidence=0.70)
    if any(p in q for p in ["rule conflict", "conflicting rule"]):
        return _decision("rule_conflicts", params=params, confidence=0.70)

    # Existing tools
    if any(p in q for p in ["first seen", "first detected", "first time", "earliest", "first appeared",
                             "first inserted", "first added", "first registered"]):
        return _decision("person_first_seen", params=params, confidence=0.65)
    if any(p in q for p in ["timeline", "movement", "track", "route", "path", "where did"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("person_timeline", params=params, confidence=0.65)
    if any(p in q for p in ["last seen", "last detected", "where is", "where was", "locate", "find"]):
        return _decision("person_last_seen", params=params, confidence=0.65)
    if any(p in q for p in ["who was seen", "who came", "who entered", "who appeared"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("people_seen_on_date", params=params, confidence=0.65)
    if any(p in q for p in ["list employees", "list visitors", "list known", "known people",
                             "who are the employees", "who are the visitors", "show employees"]):
        ptype = "employee" if "employee" in q else ("visitor" if "visitor" in q else None)
        p2 = dict(params)
        if ptype:
            p2["person_type"] = ptype
        return _decision("all_known_people", params=p2, confidence=0.70)
    if any(p in q for p in ["how many", "how any", "count", "number of", "total"]):
        if any(p in q for p in ["unknown", "stranger", "unidentified"]):
            return _decision("unknown_detection_count", params=params, confidence=0.65)
        if any(p in q for p in ["known", "identified", "recognized"]):
            return _decision("known_face_detection_count", params=params, confidence=0.65)
        if any(p in q for p in ["face", "detection", "detected", "people", "person"]):
            return _decision("face_detection_count", params=params, confidence=0.65)
        return _decision("table_record_counts", params={}, confidence=0.65)
    if any(p in q for p in ["repeated", "came back", "returned", "more than once"]):
        return _decision("repeated_unknown_faces", params=params, confidence=0.65)
    if any(p in q for p in ["unknown", "stranger", "unidentified"]):
        return _decision("latest_unknown_face_events", params=params, confidence=0.60)
    if any(p in q for p in ["anomaly", "anomalies", "incident", "alert"]):
        if name:
            return _decision("anomalies_near_person", params=params, confidence=0.60)
        return _decision("latest_anomalies", params=params, confidence=0.60)
    if any(p in q for p in ["camera", "cameras"]):
        return _decision("camera_activity_summary", params=params, confidence=0.60)
    if any(p in q for p in ["summary", "report", "overview", "brief"]):
        return _decision("daily_security_summary", params=params, confidence=0.60)

    return _decision("sql_fallback", params={}, confidence=0.3)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called by LangGraph
# ─────────────────────────────────────────────────────────────────────────────

def _expand_with_history(question: str, history: list | None) -> str:
    """
    Expand short follow-up questions using context from recent history.

    Examples:
      "what about the inactive" + prev intent=anomaly_rules  → "what about the inactive anomaly rules"
      "what about yesterday"   + prev intent=person_last_seen, name=Lina → "what about Lina yesterday"

    Only enriches when the current question is short (≤6 words) and vague.
    Returns the original question unchanged when no enrichment is needed.
    """
    if not history or len(question.split()) > 6:
        return question

    q = question.lower().strip()

    # Only enrich when the question contains a filter/status word — avoids expanding
    # unrelated follow-ups like "what about yesterday?" or "show me more"
    _STATUS_WORDS = {"inactive", "active", "disabled", "enabled", "pending",
                     "trigger", "suppress", "failed", "running", "queued"}
    q_words = {w.strip("?.,! ") for w in q.split()}
    has_status_word = bool(q_words & _STATUS_WORDS)
    if not has_status_word:
        return question

    # Only enrich clear follow-up openers — leave specific questions alone
    _FOLLOWUP_OPENERS = (
        "what about", "how about", "and the", "what of", "show me the",
        "and inactive", "and active", "what inactive", "what active",
        "the inactive", "the active",
    )
    bare = q.strip("?., ")
    is_followup = (
        any(q.startswith(p) for p in _FOLLOWUP_OPENERS)
        or bare in _STATUS_WORDS
        or (len(q.split()) <= 4 and has_status_word)
    )
    if not is_followup:
        return question

    # Find the last assistant message that has an intent we can reuse
    _CONTEXT_INTENTS = {
        "anomaly_rules":      "anomaly rules",
        "anomaly_candidates": "anomaly candidates",
        "ollama_jobs":        "ollama jobs",
        "latest_anomalies":   "anomalies",
        "unknown_face_events": "unknown face events",
        "person_last_seen":   None,  # use name only
        "person_timeline":    None,
        "person_first_seen":  None,
    }

    last_intent: str | None = None
    last_name:   str | None = None

    for msg in reversed(history or []):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        # Intent is sometimes embedded in tool tags or structured content.
        # We rely on the history entry having an "intent" key if the workflow stores it,
        # or fall back to keyword sniffing on the content string.
        stored_intent = msg.get("intent")
        if stored_intent and stored_intent in _CONTEXT_INTENTS:
            last_intent = stored_intent
            last_name = msg.get("name") or _extract_name(content)
            break
        # Keyword sniff on content as fallback
        cl = content.lower()
        for intent_key, label in _CONTEXT_INTENTS.items():
            if label and label in cl:
                last_intent = intent_key
                break
        if last_intent:
            break

    if not last_intent:
        return question

    label = _CONTEXT_INTENTS.get(last_intent)
    if not label:
        return question  # person intents need name, not safe to guess

    # Build enriched question preserving the user's modifier words
    enriched = f"{question.rstrip('?., ')} {label}".strip()
    logger.debug("History expansion: %r → %r (intent=%s)", question, enriched, last_intent)
    return enriched


def route(question: str, history: list | None = None) -> dict[str, Any]:
    """
    Route a user question to the correct investigation intent.

    Layer 0: History context expansion — enriches short follow-ups using prior intent
    Layer 1: Deterministic regex  — instant, zero LLM calls
    Layer 2: LLM semantic         — constrained JSON schema (~5-15s on warm 7B)
    Layer 3: Keyword fallback     — emergency backup if Layer 2 fails
    """
    question = question.strip()

    # Layer 0 — enrich vague follow-ups ("what about the inactive") with history context
    expanded = _expand_with_history(question, history)
    if expanded != question:
        logger.info("Follow-up expanded: %r → %r", question, expanded)
        question = expanded

    pre_params = _base_params(question)

    result = _layer1_deterministic(question)
    if result:
        return result

    try:
        result = _layer2_llm(question, pre_params)
        if result:
            return result
    except Exception as e:
        logger.warning("Layer 2 skipped: %s", e)

    return _layer3_keyword_fallback(question, pre_params)