"""
Intent router — classifies user questions into tool calls or the SQL path.

Strategy:
  1. A tiny LLM call classifies the intent and extracts entities (name, date).
     This handles typos, varied phrasing, and novel questions that a keyword list would miss.
  2. extract_date() is a fast regex pass that resolves relative expressions
     ("yesterday", "last Monday", "3 days ago") into YYYY-MM-DD before the
     LLM sees the question — so the model never has to guess today's date.
  3. If the LLM call fails for any reason we fall back to keyword matching
     so the system never hard-crashes.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Date extraction  (regex — fast, no LLM needed)
# ─────────────────────────────────────────────────────────────────────────────

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


def extract_date(question: str) -> str | None:
    """
    Return YYYY-MM-DD if a date expression is found in the question, else None.
    None means "no date mentioned" — callers should apply their own default.

    Handles:
      today / yesterday / N days ago / last week
      last <weekday> / this <weekday> / on <weekday>
      <Month> <day>  /  <day> <Month>
      YYYY-MM-DD  /  DD/MM/YYYY  /  DD-MM-YYYY
    """
    q = question.lower()
    today = date.today()

    # ISO literal 2025-04-28
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', q)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', q)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    if re.search(r'\btoday\b', q):
        return today.isoformat()

    if re.search(r'\byesterday\b', q):
        return (today - timedelta(days=1)).isoformat()

    # "3 days ago" / "two days ago"
    num_pat = '|'.join(_WORD_NUMS)
    m = re.search(rf'\b(\d+|{num_pat})\s+days?\s+ago\b', q)
    if m:
        n = int(_WORD_NUMS.get(m.group(1), m.group(1)))
        return (today - timedelta(days=n)).isoformat()

    if re.search(r'\blast\s+week\b', q):
        return (today - timedelta(days=7)).isoformat()

    wd_pat = '|'.join(re.escape(k) for k in _WEEKDAYS)

    # "last Monday"
    m = re.search(rf'\blast\s+({wd_pat})\b', q)
    if m:
        target_wd = _WEEKDAYS[m.group(1)]
        days_back = (today.weekday() - target_wd) % 7 or 7
        return (today - timedelta(days=days_back)).isoformat()

    # "this Friday" / "on Tuesday"
    m = re.search(rf'\b(?:this|on)\s+({wd_pat})\b', q)
    if m:
        target_wd = _WEEKDAYS[m.group(1)]
        days_back = (today.weekday() - target_wd) % 7
        return (today - timedelta(days=days_back)).isoformat()

    # "April 28" / "28 April"
    mon_pat = '|'.join(_MONTHS)
    m = re.search(rf'\b({mon_pat})\s+(\d{{1,2}})\b', q)
    if m:
        mon, day = _MONTHS[m.group(1)], int(m.group(2))
    else:
        m = re.search(rf'\b(\d{{1,2}})\s+({mon_pat})\b', q)
        if m:
            day, mon = int(m.group(1)), _MONTHS[m.group(2)]
        else:
            day = mon = None

    if day and mon:
        year = today.year
        try:
            d = date(year, mon, day)
            if d > today:
                d = date(year - 1, mon, day)
            return d.isoformat()
        except ValueError:
            pass

    return None  # no date expression found


# ─────────────────────────────────────────────────────────────────────────────
# LLM-based classifier
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """\
You are an intent classifier for a surveillance security chatbot.
Today's date: {today}

Your job is to pick ONE tool from the list below and extract a name and date if present.
When in doubt, always pick "sql" — it handles everything the other tools do not.

=== TOOL DEFINITIONS ===

sql
  USE FOR:
    - Counting or aggregating: "how many", "total", "count of", "number of"
    - Listing tables, cameras, employees, visitors, anomalies in general
    - Any question that does not fit a specific tool below
    - Questions with no specific person name and no specific date
    - Questions about thresholds, rules, severity, statistics
  EXAMPLES:
    "how many detected people" → sql
    "how many cameras do we have" → sql
    "list all employees" → sql
    "show anomalies today" → sql
    "what tables exist" → sql
    "how many visitors this week" → sql

last_seen
  USE FOR: finding the most recent / latest detection of a SPECIFIC NAMED person
  REQUIRES: a person name
  EXAMPLES:
    "where was Ahmed last seen" → last_seen, name=Ahmed
    "when was Sara last detected" → last_seen, name=Sara
    "where is John" → last_seen, name=John
    "most recent sighting of Maged" → last_seen, name=Maged

first_seen
  USE FOR: finding the very first / earliest detection of a SPECIFIC NAMED person
  REQUIRES: a person name
  KEYWORDS: first, earliest, initially, "first time", "when did X first", "when was X first"
  EXAMPLES:
    "when was Eng Maged first detected" → first_seen, name=Eng Maged
    "first time Ahmed appeared" → first_seen, name=Ahmed
    "earliest detection of Sara" → first_seen, name=Sara
    "when did John first enter" → first_seen, name=John

timeline
  USE FOR: full movement history of a SPECIFIC NAMED person on a date
  REQUIRES: a person name
  EXAMPLES:
    "track Ahmed's movement yesterday" → timeline, name=Ahmed
    "show Sara's timeline on Monday" → timeline, name=Sara

unknown_faces
  USE FOR: listing unidentified/unknown faces on a specific date
  EXAMPLES:
    "show unknown faces today" → unknown_faces
    "any strangers yesterday" → unknown_faces

repeated_unknowns
  USE FOR: unknown faces that appeared more than once across multiple days
  EXAMPLES:
    "did any unknown person come back" → repeated_unknowns
    "repeated unknown visitors" → repeated_unknowns

anomalies_near_face
  USE FOR: anomalies that happened near a face detection event
  EXAMPLES:
    "any anomaly when Ahmed was detected" → anomalies_near_face, name=Ahmed
    "incident near the entrance at 3pm" → anomalies_near_face

people_seen_today
  USE FOR: listing WHO (by name) was present on a specific date
  REQUIRES: the user must be asking about a specific day
  EXAMPLES:
    "who was seen today" → people_seen_today
    "who came in yesterday" → people_seen_today
    "who entered on Monday" → people_seen_today

=== INPUT ===
User question: {question}
Pre-resolved date (if any): {pre_date}

=== OUTPUT ===
Respond ONLY with valid JSON, nothing else:
{{
  "tool": "<tool name>",
  "name": "<person name exactly as written, or null>",
  "date": "<YYYY-MM-DD or null>"
}}
"""


def _llm_classify(question: str, pre_date: str | None) -> dict | None:
    """
    Ask the local LLM to classify intent + extract entities.
    Returns {"tool", "name", "date"} or None on any failure.
    """
    try:
        from model import OllamaLLM  # lazy import — avoids circular deps at module load
        llm = OllamaLLM()
        today_str = date.today().isoformat()
        prompt = _CLASSIFY_PROMPT.format(
            today=today_str,
            question=question,
            pre_date=pre_date or "none",
        )
        raw = llm.generate(prompt, temperature=0.0)

        # Strip markdown fences the model sometimes adds
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        # Extract first JSON object
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group())
        return {
            "tool": str(parsed.get("tool", "sql")).strip(),
            "name": parsed.get("name") or None,
            "date": parsed.get("date") or pre_date or None,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Keyword fallback  (used only if the LLM call fails)
# ─────────────────────────────────────────────────────────────────────────────

_STOP_WORDS = {
    'the','who','what','when','where','how','did','was','show','find','get',
    'list','today','yesterday','monday','tuesday','wednesday','thursday',
    'friday','saturday','sunday','last','this','on','at','in','near',
    'around','is','are','has','a','an','me','my','our','their',
}

def _extract_name_fallback(question: str) -> str | None:
    words = question.split()[1:]
    name_parts = []
    for w in words:
        clean = w.strip("?.,!\"'")
        if clean and clean[0].isupper() and clean.lower() not in _STOP_WORDS and len(clean) > 1:
            name_parts.append(clean)
        elif name_parts:
            # Stop accumulating when a lowercase word breaks the sequence
            break
    
    if name_parts:
        return " ".join(name_parts)
    return None


def _keyword_route(question: str, pre_date: str | None) -> dict:
    q = question.lower()
    name = _extract_name_fallback(question)

    if any(p in q for p in ["first seen","first detected","first time","first appeared",
                              "earliest","first entered","when did","first visit"]):
        if name:
            return {"tool": "first_seen", "name": name, "date": pre_date}

    if any(p in q for p in ["last seen","when was","where was","where is",
                              "recently seen", "most recent", "latest detection"]):
        if name:
            return {"tool": "last_seen", "name": name, "date": pre_date}

    if any(p in q for p in ["timeline","track","movement","where did","path of",
                              "route of","follow"]):
        if name:
            return {"tool": "timeline", "name": name, "date": pre_date}

    if any(p in q for p in ["repeated unknown","came more than once","appeared more than",
                               "came back","multiple times","more than once","repeat visitor"]):
        return {"tool": "repeated_unknowns", "name": None, "date": None}

    if any(p in q for p in ["unknown face","unknown person","stranger","unidentified",
                              "not identified"]):
        return {"tool": "unknown_faces", "name": None, "date": pre_date}

    if any(p in q for p in ["anomaly near","anomaly when","incident near","same time as",
                              "anomaly around","anomaly with"]):
        return {"tool": "anomalies_near_face", "name": name, "date": pre_date}

    if any(p in q for p in ["who was seen","who appeared","who came","who entered",
                              "who was there","who is in"]):
        return {"tool": "people_seen_today", "name": None, "date": pre_date}

    return {"tool": "sql", "name": None, "date": None}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def route(question: str) -> dict:
    """
    Returns:
        {
          "path":   "tool" | "sql",
          "tool":   "<tool_name>",   # only when path == "tool"
          "params": {...}
        }
    """
    q = question.lower()

    # ─────────────────────────────────────────────────────────────
    # Deterministic metadata routing
    # Do not let the LLM invent SQL for row counts across all tables.
    # ─────────────────────────────────────────────────────────────
    if (
        "which table has the most records" in q
        or "table has the most records" in q
        or "tables are currently empty" in q
        or "which tables are empty" in q
        or "empty tables" in q
        or "records in each table" in q
        or "record count for each table" in q
        or "how many records are in each table" in q
    ):
        return {
            "path": "tool",
            "tool": "table_record_counts",
            "params": {}
        }

    # ─────────────────────────────────────────────────────────────
    # Deterministic unknown-face-event routing
    # Avoid LLM mistakes such as:
    #   - WHERE status = 'active'
    #   - ignoring "last week"
    #   - confusing unknown_face_events with entry_logs
    # ─────────────────────────────────────────────────────────────
    if "unknown face event" in q or "unknown face events" in q:
        params = {"limit": 10}

        # Extract explicit limit if user says "latest 20", "last 5", etc.
        m = re.search(r"\b(?:latest|last|show me|show)\s+(\d+)\b", q)
        if m:
            try:
                params["limit"] = int(m.group(1))
            except ValueError:
                params["limit"] = 10

        if "last week" in q or "last 7 days" in q or "past week" in q:
            params["days_back"] = 7

        if "today" in q:
            params["days_back"] = 1

        if "last 24 hours" in q or "past 24 hours" in q:
            params["days_back"] = 1

        if "unreviewed" in q or "not reviewed" in q or "not been reviewed" in q:
            params["only_unreviewed"] = True

        if "reviewed" in q and not (
            "unreviewed" in q or "not reviewed" in q or "not been reviewed" in q
        ):
            params["only_unreviewed"] = False

        return {
            "path": "tool",
            "tool": "unknown_face_events",
            "params": params
        }

    # Step 1: fast regex date resolution
    pre_date = extract_date(question)

    # Step 2: LLM classification, keywords only if LLM fails
    classified = _llm_classify(question, pre_date) or _keyword_route(question, pre_date)

    tool = classified.get("tool", "sql")
    name = classified.get("name")
    d = classified.get("date")   # None = "not mentioned"

    if tool == "sql":
        return {
            "path": "sql",
            "tool": None,
            "params": {}
        }

    # ─────────────────────────────────────────────────────────────
    # Tool-specific params
    # ─────────────────────────────────────────────────────────────

    if tool == "last_seen":
        # date is optional — None means "all-time most recent"
        return {
            "path": "tool",
            "tool": "last_seen",
            "params": {
                "name": name,
                "target_date": d
            }
        }

    if tool == "first_seen":
        # date is optional — None means "all-time earliest"
        return {
            "path": "tool",
            "tool": "first_seen",
            "params": {
                "name": name,
                "target_date": d
            }
        }

    if tool == "timeline":
        return {
            "path": "tool",
            "tool": "timeline",
            "params": {
                "name": name,
                "target_date": d or date.today().isoformat()
            }
        }

    if tool == "unknown_faces":
        # TEMP SAFETY:
        # Do not use the old handwritten unknown_faces tool because it queries
        # entry_logs + detected_people instead of the real unknown_face_events table.
        # Let generic unknown-face wording go through SQL unless the user explicitly
        # says "unknown face events", which is handled above.
        return {
            "path": "sql",
            "tool": None,
            "params": {}
        }

    if tool == "repeated_unknowns":
        return {
            "path": "tool",
            "tool": "repeated_unknowns",
            "params": {}
        }

    if tool == "anomalies_near_face":
        params: dict = {}
        if name:
            params["person_name"] = name

        return {
            "path": "tool",
            "tool": "anomalies_near_face",
            "params": params
        }

    if tool == "people_seen_today":
        return {
            "path": "tool",
            "tool": "people_seen_today",
            "params": {
                "target_date": d or date.today().isoformat()
            }
        }

    # Safety net
    return {
        "path": "sql",
        "tool": None,
        "params": {}
    }