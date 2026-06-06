"""VAD Anomaly Rules sub-package.

Provides DB-backed rule management and a deterministic rule-matching engine
for the Deep Gate reasoning pipeline.  Rules are stored in the
``vad_reasoning_rules`` Postgres table and can be created / toggled at runtime
via the admin API without restarting the service.

Public API
----------
- ``load_active_vad_rules(db, conn)``  – load active rules from the DB
- ``rule_matches(rule, ctx, vlm)``     – deterministic single-rule match
- ``deterministic_rule_matches(...)``  – match all rules, split by type
- ``serialize_rules_for_llm(rules)``   – compact representation for the LLM prompt
- ``RULES_VERSION``                    – version string included in every result
"""

from .vad_rules_engine import (
    RULES_VERSION,
    deterministic_rule_matches,
    load_active_vad_rules,
    rule_matches,
    serialize_rules_for_llm,
)

__all__ = [
    "RULES_VERSION",
    "deterministic_rule_matches",
    "load_active_vad_rules",
    "rule_matches",
    "serialize_rules_for_llm",
]
