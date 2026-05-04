"""
Intent Router — Surveillance Investigation Chatbot
===================================================

How it works:
  Layer 1 – Deterministic rules   (instant, zero LLM, handles unambiguous cases)
  Layer 2 – LLM semantic router   (handles ALL rephrasing — returns JSON, NEVER SQL)
  Layer 3 – Keyword fallback      (safety net if LLM call fails completely)

The LLM's only job: understand what the user wants → return {"intent": "...", "name": "...", ...}
The LLM never writes SQL. Python functions handle all database queries.

This means "locate ahmed", "find ahmed", "where is ahmed", "has ahmed been spotted",
"which camera last saw ahmed", "ahmed's last location" all produce the same result.
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
    # Action/counting words that must NOT be treated as person names
    "count", "total", "number", "many", "much", "every", "everything",
    "everyone", "everybody", "no", "nobody", "each", "same",
    # Registry/people-list words
    "known", "people", "employees", "employee", "visitors", "visitor", "staff",
    "registered", "names", "identities", "system", "database", "records",
    "enrolled", "profiles", "identities", "identity", "registry",
    # Surveillance domain words
    "anomaly", "anomalies", "anomalie", "alert", "alerts", "incident",
    "incidents", "logs", "log", "camera", "cameras", "detection", "detections",
    "security", "summary", "report", "activity", "events",
    # Navigation/tracking words that follow a name
    "location", "locations", "path", "route", "history", "sighting",
    "sightings", "track", "tracking", "follow", "following",
    # Building/infrastructure words
    "building", "entrance", "hall", "corner", "room", "lab", "labs",
    "department", "departments", "administration", "engineering",
    "rule", "rules", "schedule", "schedules", "threshold", "description",
    "table", "tables", "pointing", "belong", "belongs",
}


def extract_date(question: str) -> str | None:
    """Resolve any date expression to YYYY-MM-DD. Returns None if no date found."""
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

    # NOTE: "last week" is a date RANGE — handled by _extract_days_back()
    # DO NOT resolve to a single date here.
    # if re.search(r"\blast\s+week\b", q):
    #     return (today - timedelta(days=7)).isoformat()

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

    # Bare weekday name ("tuesday") without last/this/on prefix
    # → resolve to the most recent past occurrence of that day
    m = re.search(rf"\b({wd_pat})\b", q)
    if m:
        preceding = q[:m.start()]
        if not re.search(r"\b(?:last|this|on|next)\s*$", preceding):
            target = _WEEKDAYS[m.group(1)]
            days_back = (today.weekday() - target) % 7 or 7
            return (today - timedelta(days=days_back)).isoformat()

    # dd-mm or dd/mm (no year) — "29-4", "29/4"
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
    # Try "29 april" / "29 april4" (day before month) FIRST — higher priority
    # The \b after the month allows optional trailing digit typos like "april4"
    m = re.search(rf"\b(\d{{1,2}})\s+({mon_pat})", q)
    if m:
        day, mon = int(m.group(1)), _MONTHS[m.group(2)]
    else:
        # Then try "april 29" (month before day, with space)
        m = re.search(rf"\b({mon_pat})\s+(\d{{1,2}})\b", q)
        if m:
            mon, day = _MONTHS[m.group(1)], int(m.group(2))
        else:
            # Finally no-space variants: "april29" or "29april"
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
    # Negative lookahead prevents matching "3pm" or "3am" as a limit
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
    Handles both title-case ("Maged") and lowercase ("maged") — real users
    almost never capitalize names in chat messages.
    """
    # Strategy 1: one or two words after investigation keywords, stopping at stop words.
    # Pattern: keyword → space → 1-2 name words (each NOT a stop word)
    kw = (
        r"for|of|about|near|around|track|follow|locate|find|"
        r"where is|where was|last seen|first seen|first detected|last detected|"
        r"timeline for|movement of|path of|sighting of|"
        r"when was|when did|spotted|detected|seen|appeared|entered"
    )
    m = re.search(
        rf"\b(?:{kw})\s+([a-zA-Z][a-z'-]+(?:\s+[a-zA-Z][a-z'-]+)?)",
        question,
        re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip("?.,!\"' ")
        # Take only the leading words that are not stop words
        words = raw.split()
        name_parts = []
        for w in words:
            # Strip possessive 's before checking
            clean = re.sub(r"['']\.?s$", "", w, flags=re.IGNORECASE)
            if clean.lower() in _STOP_WORDS:
                break
            name_parts.append(clean)
        if name_parts:
            candidate = " ".join(name_parts)
            if candidate.lower() not in _STOP_WORDS and len(candidate) > 1:
                return candidate.title()

    # Strategy 2: possessive ("maged's movements")
    m = re.search(r"\b([A-Za-z][a-zA-Z'-]+(?:\s+[A-Za-z][a-zA-Z'-]+){0,2})['']\.?s\b",
                  question, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # Remove trailing action/stop words from the possessive name
        name_words = name.split()
        clean_parts = []
        for w in name_words:
            if w.lower() in _STOP_WORDS:
                break
            clean_parts.append(w)
        if clean_parts:
            name = " ".join(clean_parts)
            if name.lower() not in _STOP_WORDS:
                return name.title()

    # Strategy 3: verb + name — "find ahmed", "track maged", "locate sara"
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

    # Strategy 4: name appears BEFORE a keyword — "ahmed was seen", "first time lina appeared"
    # Catches patterns where the name precedes the verb/keyword
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

    # Strategy 5: title-cased words (last resort — for properly capitalized names)
    parts: list[str] = []
    for word in question.split():
        clean = word.strip("?.,!\"'")
        # Strip possessive 's
        clean = re.sub(r"['']\.?s$", "", clean, flags=re.IGNORECASE)
        if clean and clean[0].isupper() and clean.lower() not in _STOP_WORDS and len(clean) > 1:
            parts.append(clean)
        elif parts:
            break
    if parts:
        return " ".join(parts)

    return None


def _base_params(question: str) -> dict[str, Any]:
    """Extract all parameter candidates from the question (no LLM needed)."""
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
# Only handles cases where intent is 100% clear from the text alone.
# ─────────────────────────────────────────────────────────────────────────────

_SMALL_TALK_RE = re.compile(
    r"^\s*(hello|hi\b|hey\b|hiya|howdy|how are you|what can you do|"
    r"help\s*$|thanks|thank you|who are you|what is your name|"
    r"what'?s your name|good morning|good afternoon|good evening)\b",
    re.IGNORECASE,
)


def _layer1_deterministic(question: str) -> dict[str, Any] | None:
    """
    Instant deterministic routing — no LLM needed.
    Handles all unambiguous patterns covering ~70% of real surveillance questions.
    Checked in priority order: most specific first, most generic last.
    """
    q = question.lower().strip()
    params = _base_params(question)

    # ── Small talk ────────────────────────────────────────────────────────────
    if _SMALL_TALK_RE.search(q):
        return _decision("small_talk", confidence=1.0)

    # ── Event ID present → route by action verb first ─────────────────────────
    eid = params.get("event_id")
    if eid is not None:
        if any(p in q for p in ["investigate", "full report", "complete report", "full investigation"]):
            return _decision("investigate_unknown_face_event",
                             params={**params, "threshold": 0.60}, confidence=1.0)
        if any(p in q for p in ["who is", "identify", "possible match", "known match",
                                 "closest known", "who could", "identity"]):
            return _decision("possible_identity_match",
                             params={**params, "threshold": 0.55}, confidence=1.0)
        if any(p in q for p in ["similar", "appeared before", "seen before", "came back",
                                 "has this person", "been seen before"]):
            return _decision("similar_unknown_faces",
                             params={**params, "threshold": 0.60}, confidence=1.0)
        if any(p in q for p in ["anomaly", "anomalies", "incident", "alert near", "incident near"]):
            return _decision("anomalies_near_unknown_event", params=params, confidence=1.0)
        if any(p in q for p in ["details", "detail", "info about event", "tell me about event",
                                 "what is event", "show event"]):
            return _decision("unknown_face_event_details", params=params, confidence=1.0)

    # ── Registry / known people (before person-specific intents) ──────────────
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
        # "everyone" patterns — must NOT be treated as a person name
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
        "how many unknown faces", "how many known faces",
        "how any unknown face events", "how any known face events", "how any events",
        "count departments", "count labs", "count rules", "count cameras",
        "count employees", "count visitors", "total departments", "total labs",
        "total cameras", "total employees", "total visitors", "total rules",
        "number of departments", "number of labs", "number of cameras",
        "number of employees", "number of visitors", "number of rules",
        "count all", "total records",
    ]):
        return _decision("table_record_counts", params={}, confidence=1.0)

    # ── Admin/System Tables (Direct Lookups) ──────────────────────────────────
    if any(p in q for p in ["anomaly candidates", "pending candidates", "candidates"]):
        return _decision("anomaly_candidates", params=params, confidence=1.0)
    if any(p in q for p in ["candidate decision", "candidate review", "confirmed anomalies", "dismissed anomalies", "decide on candidate"]):
        return _decision("anomaly_candidate_review", params=params, confidence=1.0)
    if any(p in q for p in ["jobs", "queue", "failed jobs", "running jobs", "ollama jobs"]):
        return _decision("ollama_jobs", params=params, confidence=1.0)
    if any(p in q for p in ["scene window", "camera window", "flagged window"]):
        return _decision("scene_window_embeddings", params=params, confidence=1.0)
    if any(p in q for p in ["anomaly rules", "intrusion rules", "suppress rules", "loitering rules", "active rules", "rules apply"]):
        return _decision("anomaly_rules", params=params, confidence=1.0)
    if any(p in q for p in ["edge device", "devices registered", "edge devices"]):
        return _decision("edge_devices", params=params, confidence=1.0)
    if any(p in q for p in ["behavior model", "behavior models"]):
        return _decision("normal_behavior_models", params=params, confidence=1.0)
    if any(p in q for p in ["rule conflict", "rule conflicts"]):
        return _decision("rule_conflicts", params=params, confidence=1.0)

    # ── Daily / security summary ──────────────────────────────────────────────
    if any(p in q for p in [
        "daily summary", "security summary", "daily report", "security report",
        "security overview", "what happened today", "what happened yesterday",
        "today's summary", "today's report", "summary for today",
    ]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("daily_security_summary", params=params, confidence=1.0)

    # ── Camera activity ───────────────────────────────────────────────────────
    if any(p in q for p in [
        "camera activity", "camera summary", "camera stats", "camera statistics",
        "busiest camera", "most active camera", "detections by camera",
        "detections per camera", "which camera has the most",
    ]):
        return _decision("camera_activity_summary", params=params, confidence=1.0)

    # ── Repeated unknowns ─────────────────────────────────────────────────────
    if any(p in q for p in [
        "repeated unknown", "stranger come back", "stranger return", "unknown came back",
        "unknown returned", "repeated visitor", "appeared more than once",
        "came back more", "suspicious repeat",
    ]):
        params.setdefault("days_back", 7)
        return _decision("repeated_unknown_faces", params=params, confidence=1.0)

    # ── Unknown face event listing ────────────────────────────────────────────
    if any(p in q for p in [
        "latest unknown face", "latest unknown faces", "show unknown face events",
        "list unknown face events", "recent unknown face", "unknown face events",
        "show me unknowns", "list unknowns", "unreviewed unknowns", "pending unknowns",
        "show strangers", "list strangers", "recent strangers", "show recent strangers",
        "latest strangers",
    ]):
        if any(p in q for p in ["unreviewed", "pending", "not assigned", "unassigned"]):
            params["only_unreviewed"] = True
        return _decision("latest_unknown_face_events", params=params, confidence=1.0)

    # ── Anomaly listing ───────────────────────────────────────────────────────
    # Note: "anomalies near <person>" is caught in the person-specific block below.
    # Here we only catch general anomaly listing with no person name.
    if any(p in q for p in [
        "latest anomalies", "show anomalies", "list anomalies", "recent anomalies",
        "show anomaly logs", "list anomaly logs", "recent security incidents",
        "show incidents", "list incidents", "any incidents today", "any alerts today",
        "security alerts", "show alerts", "recent alerts", "anomaly logs",
        # Typo-tolerant: catch common misspellings
        "latest anomalie", "show anomalie", "show latest anomaly",
    ]):
        return _decision("latest_anomalies", params=params, confidence=1.0)

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

    # ── Person-specific intents (require name extraction) ─────────────────────
    # Only fire if we can actually extract a name
    name = _extract_name(question)

    if name:
        params["name"] = name
        if any(p in q for p in [
            "anomaly near", "anomalies near", "incident near", "alert near",
            "anomaly when", "incident when", "alert when",
        ]):
            return _decision("anomalies_near_person", params=params, confidence=1.0)

        if any(p in q for p in [
            "first seen", "first detected", "first time", "earliest", "first appeared",
            "first entry", "first time seen", "when first", "earliest detection",
        ]):
            return _decision("person_first_seen", params=params, confidence=1.0)

        if any(p in q for p in [
            "timeline", "movement", "movements", "route", "path", "track",
            "where did", "which cameras", "cameras visited", "all detections for",
        ]):
            params.setdefault("target_date", date.today().isoformat())
            return _decision("person_timeline", params=params, confidence=1.0)

        if any(p in q for p in [
            "last seen", "last detected", "most recent", "recently seen",
            "where is", "where was", "locate", "find", "spotted", "current location",
            "latest detection", "last sighting", "last location",
        ]):
            return _decision("person_last_seen", params=params, confidence=1.0)

        # ── Name extracted but no specific keyword matched ────────────────────
        # Default to person_last_seen — most common intent for a bare name query.
        # e.g. "ahmed", "tell me about maged", "maged?"
        return _decision("person_last_seen", params=params, confidence=0.85)



# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — LLM semantic classifier
#
# Uses a SYSTEM prompt (not a user-turn) so the model is primed for structured
# output rather than conversational response. This is more reliable for small
# models like qwen2.5-coder:3b.
#
# Uses FEW-SHOT JSON EXAMPLES instead of prose instructions — small models
# follow demonstrations far more reliably than instruction lists.
# ─────────────────────────────────────────────────────────────────────────────

# The system prompt is the model's standing instructions.
# It is short and imperative — small models ignore long preambles.
_SYSTEM_PROMPT = """\
You are a JSON intent classifier for a surveillance security chatbot.
Today: {today}

OUTPUT RULES — CRITICAL:
- Output ONLY a single JSON object. Nothing else. No explanation. No markdown. No SQL.
- All string values must be properly quoted.
- Use null (not "null", not "") for absent fields.
- event_id must be an integer, never a string.

VALID INTENTS:
person_last_seen, person_first_seen, person_timeline,
people_seen_on_date, unknown_detection_count, known_face_detection_count,
face_detection_count, latest_unknown_face_events, unknown_face_event_details,
repeated_unknown_faces,
similar_unknown_faces, possible_identity_match, investigate_unknown_face_event,
latest_anomalies, anomalies_near_person, anomalies_near_unknown_event,
camera_activity_summary, daily_security_summary, table_record_counts,
all_known_people, anomaly_candidates, anomaly_candidate_review, ollama_jobs,
scene_window_embeddings, anomaly_rules, edge_devices, normal_behavior_models,
rule_conflicts, sql_fallback

INTENT RULES:
- person_last_seen/first_seen/timeline: requires a person name
- people_seen_on_date: who was seen on a date, no single name needed
- unknown_detection_count: counting unknown faces, use pre_date if given
- known_face_detection_count: counting known/identified faces
- face_detection_count: counting ALL detections (known + unknown)
- latest_unknown_face_events: listing unknown face events (not counting)
- similar_unknown_faces/possible_identity_match/investigate_unknown_face_event: requires event_id
- anomalies_near_person: requires a person name
- anomalies_near_unknown_event: requires event_id
- all_known_people: list employees/visitors from registry (no date)
- sql_fallback: only if nothing else fits

JSON SCHEMA:
{{"intent":"...","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}}"""

# Minimal few-shot examples — only 8 to keep the prompt well under 2K tokens.
# The model just needs to see the JSON schema pattern; more examples waste context.
_FEW_SHOT_EXAMPLES = [
    ("find maged",
     '{"intent":"person_last_seen","name":"Maged","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("show ahmed movements yesterday",
     '{"intent":"person_timeline","name":"Ahmed","target_date":"{yesterday}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("when was lina first detected",
     '{"intent":"person_first_seen","name":"Lina","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("who was seen today",
     '{"intent":"people_seen_on_date","name":null,"target_date":"{today}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("how many unknown faces today",
     '{"intent":"unknown_detection_count","name":null,"target_date":"{today}","event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("investigate unknown face event 274",
     '{"intent":"investigate_unknown_face_event","name":null,"target_date":null,"event_id":274,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("any anomalies near ahmed",
     '{"intent":"anomalies_near_person","name":"Ahmed","target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
    ("who are the known people",
     '{"intent":"all_known_people","name":null,"target_date":null,"event_id":null,"limit":null,"days_back":null,"hour":null,"only_unreviewed":null,"person_type":null}'),
]


def _build_few_shot_user_message(question: str, pre_date: str | None, event_id: int | None) -> str:
    """
    Build the user-turn message: few-shot examples followed by the real question.
    We inject today/yesterday into example outputs so the model sees realistic dates.
    """
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    lines = ["EXAMPLES (input → output):"]
    for q, out in _FEW_SHOT_EXAMPLES:
        out_filled = out.replace("{today}", today_str).replace("{yesterday}", yesterday_str)
        lines.append(f'Input: "{q}"')
        lines.append(f"Output: {out_filled}")
        lines.append("")

    lines.append("Now classify:")
    lines.append(f'Input: "{question}"')
    if pre_date:
        lines.append(f"(pre-resolved date: {pre_date})")
    if event_id is not None:
        lines.append(f"(pre-extracted event_id: {event_id})")
    lines.append("Output:")
    return "\n".join(lines)


_INTENT_CACHE: dict[str, str] = {}

def _normalize_question(question: str) -> str:
    """Normalize names, dates, and IDs so similar questions share a cache key."""
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
    LLM semantic classification using system prompt + few-shot examples.
    Uses llm.classify() which sends a proper system message rather than a user message,
    keeping the model in structured-output mode rather than conversational mode.
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
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()

            # Extract the first JSON object found (model may add trailing text)
            m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if not m:
                return None
            raw_json = m.group()
            # Don't cache sql_fallback, it's safer to re-evaluate
            if "sql_fallback" not in raw_json:
                _INTENT_CACHE[norm_q] = raw_json

        parsed = json.loads(raw_json)
        intent = canonical_intent(parsed.get("intent", "sql_fallback"))

        # Start with regex-extracted params — more reliable for dates and IDs
        params = dict(pre_params)

        # Merge LLM-extracted values, never overriding regex-resolved dates/IDs
        for key in ("name", "target_date", "event_id", "limit", "days_back",
                    "hour", "only_unreviewed", "person_type"):
            val = parsed.get(key)
            if val is None or val == "null" or val == "":
                continue
            if key in ("target_date", "event_id") and key in params:
                continue  # regex wins for structured values
            params[key] = val

        # Last resort: if intent needs name but LLM missed it, try regex
        if "name" in required_params(intent) and not params.get("name"):
            fallback_name = _extract_name(question)
            if fallback_name:
                params["name"] = fallback_name

        return _decision(intent, params=params, confidence=0.88)

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
    # Also try extracting a name from "near X" / "about X" / "for X" with any casing
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

    if any(p in q for p in ["first seen", "first detected", "first time", "earliest", "first appeared"]):
        return _decision("person_first_seen", params=params, confidence=0.65)
    if any(p in q for p in ["timeline", "movement", "track", "route", "path", "where did"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("person_timeline", params=params, confidence=0.65)
    if any(p in q for p in ["last seen", "last detected", "where is", "where was", "locate", "find"]):
        return _decision("person_last_seen", params=params, confidence=0.65)
    if any(p in q for p in ["who was seen", "who came", "who entered", "who appeared"]):
        params.setdefault("target_date", date.today().isoformat())
        return _decision("people_seen_on_date", params=params, confidence=0.65)
    if any(p in q for p in [
        "list employees", "list visitors", "list known", "known people",
        "who are the employees", "who are the visitors", "show employees",
        "all employees", "all visitors",
    ]):
        ptype = None
        if "employee" in q:
            ptype = "employee"
        elif "visitor" in q:
            ptype = "visitor"
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
        # Generic "how many X" (labs, departments, rules, cameras, etc.)
        # Route to table_record_counts — answers deterministically, no LLM needed.
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
    if any(p in q for p in ["summary", "report", "overview"]):
        return _decision("daily_security_summary", params=params, confidence=0.60)

    return _decision("sql_fallback", params={}, confidence=0.3)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called by LangGraph
# ─────────────────────────────────────────────────────────────────────────────

def route(question: str, history: list | None = None) -> dict[str, Any]:
    """
    Route a user question to the correct investigation intent.
    LangGraph calls this from its route_intent node.

    Layers:
      1. Deterministic regex  — instant, zero LLM calls
      2. LLM semantic         — handles free-form rephrasing (classify, ~3-8s on warm model)
      3. Keyword fallback     — emergency backup if Layer 2 fails
    """
    question = question.strip()
    pre_params = _base_params(question)

    # Layer 1: instant deterministic check
    result = _layer1_deterministic(question)
    if result:
        return result

    # Layer 2: LLM semantic classification
    # This now works reliably because prompts.py is capped at 6K chars,
    # keeping Ollama free — classify() finishes in 3-8s on a warm model.
    try:
        result = _layer2_llm(question, pre_params)
        if result:
            return result
    except Exception as e:
        logger.warning(f"Layer 2 skipped due to LLM failure: {e}")

    # Layer 3: keyword fallback
    return _layer3_keyword_fallback(question, pre_params)