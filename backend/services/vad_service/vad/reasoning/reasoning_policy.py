from __future__ import annotations

from typing import Any

from .reasoning_schema import (
    DeepReasoningContext,
    LlmPolicyReview,
    PythonFinalResult,
    VlmVisualReview,
    STRONG_VISUAL_EVENT_TYPES,
    model_to_dict,
)
# Import deterministic matcher from the new DB-backed rules module.
# reasoning_policy does not load rules from DB itself; the worker passes
# the already-loaded rule list in.
from ..vad_anomaly_rules import deterministic_rule_matches, RULES_VERSION

POLICY_VERSION = "deep_reasoning_policy_v2_vlm_llm_python_guardrails"
SEVERITY_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
RANK_SEVERITY = {v: k for k, v in SEVERITY_RANK.items()}


def _action_for(decision: str, severity: str) -> str:
    if decision == "NO":
        return "ignore"
    if decision == "UNCERTAIN":
        return "review_only"
    if severity in {"HIGH", "CRITICAL"}:
        return "urgent_alert"
    return "alert_operator"


def _min_severity(current: str, minimum: str) -> str:
    return RANK_SEVERITY[max(SEVERITY_RANK.get(current, 1), SEVERITY_RANK.get(minimum, 1))]


def _cap_severity_for_decision(decision: str, severity: str) -> str:
    if decision == "NO" and severity not in {"NONE", "LOW"}:
        return "LOW"
    if decision == "UNCERTAIN" and severity in {"HIGH", "CRITICAL"}:
        return "MEDIUM"
    if decision == "YES" and severity == "NONE":
        return "LOW"
    return severity


# Words that suggest the evidence is grounded in physical/visual observation
# (body parts, objects, actions, spatial descriptors).  Evidence containing at
# least one of these is treated as visual rather than score-based.
_VISUAL_EVIDENCE_WORDS = frozenset({
    # Body and posture
    "fall", "floor", "collapse", "body", "lying", "prone", "person",
    "arm", "leg", "head", "hand", "torso", "posture", "limb",
    # Motion and actions
    "running", "sprinting", "rapid", "fast", "movement", "moving", "rushing",
    "walking", "stumbling", "crawling", "reaching",
    # Equipment and objects
    "equipment", "machine", "door", "window", "wall", "object", "chair",
    "table", "cabinet", "panel", "device", "rack", "screen",
    # Security / access
    "intrusion", "intruder", "suspicious", "unauthorized",
    "entering", "exiting", "climbing",
    # Appearance and location
    "visible", "seen", "detected", "observed", "appeared", "near",
    "behind", "under", "against", "beside", "inside", "outside",
})

# Words that indicate the evidence is about scores/metrics, not visual facts.
_SCORE_EVIDENCE_WORDS = frozenset({
    "score", "threshold", "ratio", "deep", "embedding", "distance",
    "above", "knn", "percentile", "deviation", "anomaly score",
})


def _only_score_based_evidence(vlm: VlmVisualReview) -> bool:
    """Return True if the VLM anomaly evidence contains no concrete visual facts.

    Evidence is score-based if it:
    - Contains score/metric vocabulary AND
    - Does NOT contain any physical/visual observation vocabulary.

    This is more robust than pure keyword matching because it requires BOTH
    conditions — preventing a sentence like "the person was running; score was
    high" from being wrongly classified as score-only.
    """
    if not vlm.anomaly_evidence:
        return True
    joined = " ".join(vlm.anomaly_evidence).lower()
    words = {w.strip(".,!?;:()") for w in joined.split()}
    has_visual = bool(words & _VISUAL_EVIDENCE_WORDS)
    # If there is ANY concrete visual word, the evidence is not score-only.
    if has_visual:
        return False
    has_score = bool(words & _SCORE_EVIDENCE_WORDS)
    return has_score


def apply_python_final_guardrails(
    *,
    ctx: DeepReasoningContext,
    vlm: VlmVisualReview,
    llm: LlmPolicyReview,
    rules: list[dict[str, Any]],
    vlm_parse_info: dict[str, Any] | None = None,
    llm_parse_info: dict[str, Any] | None = None,
) -> tuple[PythonFinalResult, dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    decision = llm.policy_alert_decision
    severity = llm.policy_severity
    confidence = float(llm.policy_confidence)
    recommended_action = llm.recommended_action

    vlm_parse_error = (vlm_parse_info or {}).get("parse_error")
    llm_parse_error = (llm_parse_info or {}).get("parse_error")
    if vlm_parse_error:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.30)
        actions.append({"rule_id": "VLM_PARSE_OR_SCHEMA_FALLBACK", "effect": "forced UNCERTAIN", "reason": str(vlm_parse_error)})
    if llm_parse_error:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.30)
        actions.append({"rule_id": "LLM_PARSE_OR_SCHEMA_FALLBACK", "effect": "forced UNCERTAIN", "reason": str(llm_parse_error)})

    if not llm.evidence_assessment.uses_only_vlm_evidence:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.40)
        actions.append({"rule_id": "LLM_USED_NON_VLM_VISUAL_FACTS", "effect": "downgraded to UNCERTAIN", "reason": "LLM reported that it did not rely only on VLM evidence."})

    strong_visual = bool(vlm.anomaly_evidence and vlm.event_type in STRONG_VISUAL_EVENT_TYPES)
    if decision == "YES" and not vlm.anomaly_evidence:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.45)
        actions.append({"rule_id": "YES_WITHOUT_VLM_ANOMALY_EVIDENCE", "effect": "downgraded YES to UNCERTAIN", "reason": "LLM selected YES but the VLM anomaly_evidence list is empty."})

    if decision == "YES" and _only_score_based_evidence(vlm):
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.45)
        actions.append({"rule_id": "YES_WITH_SCORE_ONLY_EVIDENCE", "effect": "downgraded YES to UNCERTAIN", "reason": "Score/threshold evidence alone is not visual anomaly evidence."})

    ratio = ctx.score_ratio
    if decision == "YES" and ratio is not None and ratio < 1.15 and not strong_visual:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.50)
        actions.append({"rule_id": "WEAK_RATIO_REQUIRES_STRONG_VISUAL_EVIDENCE", "effect": "downgraded YES to UNCERTAIN", "reason": f"score_ratio={ratio:.4f} is below 1.15 and VLM did not provide a strong visual anomaly type."})

    if decision == "YES" and vlm.event_type == "unclear_visual_evidence":
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.45)
        actions.append({"rule_id": "UNCLEAR_VISUAL_EVIDENCE_CANNOT_CONFIRM_YES", "effect": "downgraded YES to UNCERTAIN", "reason": "VLM classified event_type as unclear_visual_evidence."})

    if decision == "YES" and vlm.image_quality in {"POOR", "UNUSABLE"} and not strong_visual:
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        confidence = min(confidence, 0.45)
        actions.append({"rule_id": "POOR_IMAGE_QUALITY_REQUIRES_STRONG_EVIDENCE", "effect": "downgraded YES to UNCERTAIN", "reason": f"image_quality={vlm.image_quality}."})

    if confidence < 0.45 and decision == "YES":
        decision = "UNCERTAIN"
        severity = "LOW"
        recommended_action = "review_only"
        actions.append({"rule_id": "LOW_CONFIDENCE_CANNOT_CONFIRM_YES", "effect": "downgraded YES to UNCERTAIN", "reason": f"policy_confidence={confidence:.2f} is below 0.45."})

    # Deterministic verification of project rules. LLM may explain rules, but Python records/verifies exact matches.
    deterministic_rules = deterministic_rule_matches(ctx=ctx, vlm=vlm, rules=rules)
    for rule in deterministic_rules["matched_suppress_rules"]:
        effect = rule.get("effect") or {}
        if decision in {"YES", "UNCERTAIN"}:
            decision = effect.get("policy_alert_decision", decision)
            severity = effect.get("policy_severity", severity)
            recommended_action = effect.get("recommended_action", recommended_action)
            confidence = min(confidence, 0.70)
            actions.append({"rule_id": rule.get("rule_id"), "effect": "applied suppress rule", "reason": rule.get("reason")})

    for rule in deterministic_rules["matched_trigger_rules"]:
        effect = rule.get("effect") or {}
        if decision == "YES" and strong_visual:
            severity = _min_severity(severity, str(effect.get("minimum_severity") or severity))
            recommended_action = str(effect.get("recommended_action") or recommended_action)
            actions.append({"rule_id": rule.get("rule_id"), "effect": "applied trigger rule", "reason": rule.get("reason")})
        elif decision != "YES":
            actions.append({"rule_id": rule.get("rule_id"), "effect": "trigger not applied", "reason": "Trigger rules cannot upgrade a non-YES decision without a visually confirmed anomaly."})

    severity = _cap_severity_for_decision(decision, severity)
    normalized_action = _action_for(decision, severity)
    # Preserve save_for_dataset for NO/UNCERTAIN when a suppress/calibration path chose it.
    if not (decision in {"NO", "UNCERTAIN"} and recommended_action == "save_for_dataset"):
        if recommended_action != normalized_action:
            actions.append({"rule_id": "RECOMMENDED_ACTION_NORMALIZED", "effect": f"{recommended_action} -> {normalized_action}", "reason": "Recommended action must match final decision/severity."})
        recommended_action = normalized_action

    reason = llm.decision_reason.strip() or vlm.visual_decision_reason
    if actions:
        reason = reason + " Python guardrails were applied to keep the final decision consistent with visible evidence, score ratio, and rules."

    final = PythonFinalResult(
        final_alert_decision=decision,
        final_severity=severity,
        final_confidence=max(0.0, min(1.0, confidence)),
        final_recommended_action=recommended_action,
        final_decision_reason=reason,
        guardrail_actions=actions,
    )
    rules_result = {
        "rules_version": RULES_VERSION,
        "llm_matched_trigger_rules": [r.model_dump(mode="json") for r in llm.matched_trigger_rules],
        "llm_matched_suppress_rules": [r.model_dump(mode="json") for r in llm.matched_suppress_rules],
        "deterministic_matched_trigger_rules": deterministic_rules["matched_trigger_rules"],
        "deterministic_matched_suppress_rules": deterministic_rules["matched_suppress_rules"],
        "rule_reasoning": llm.rule_reasoning,
    }
    return final, rules_result


def build_structured_result(
    *,
    ctx: DeepReasoningContext,
    vlm: VlmVisualReview,
    llm: LlmPolicyReview,
    final: PythonFinalResult,
    rules_result: dict[str, Any],
    image_object_keys: list[str],
    raw_vlm_output: str,
    raw_llm_output: str | None,
    vlm_parse_info: dict[str, Any] | None,
    llm_parse_info: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": ctx.event_id,
        "case_id": ctx.case_id,
        "gate_name": ctx.gate_name,
        "deep_gate": {
            "peak_score": ctx.deep_score,
            "threshold_value": ctx.threshold_value,
            "score_ratio": ctx.score_ratio,
            "ratio_band": ctx.ratio_band(),
            "gate_decision": "candidate",
        },
        "vlm_visual_review": model_to_dict(vlm),
        "llm_policy_review": model_to_dict(llm),
        "rules_result": rules_result,
        "python_final_result": model_to_dict(final),
        "image_object_keys": image_object_keys,
        "parse_info": {
            "vlm": vlm_parse_info or {},
            "llm": llm_parse_info or {},
        },
        "raw_vlm_response_preview": (raw_vlm_output or "")[:2000],
        "raw_llm_response_preview": (raw_llm_output or "")[:2000] if raw_llm_output else None,
        "policy_version": POLICY_VERSION,
        "rules_version": RULES_VERSION,
    }
