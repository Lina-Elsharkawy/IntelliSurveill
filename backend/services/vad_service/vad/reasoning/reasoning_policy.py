from __future__ import annotations

from typing import Any

from .reasoning_schema import (
    DeepReasoningContext,
    PoseReasoningContext,
    LlmPolicyReview,
    PythonFinalResult,
    VlmVisualReview,
    model_to_dict,
)
from ..vad_anomaly_rules import deterministic_rule_matches, RULES_VERSION

# Paper-backed policy layer:
# - AnomalyRuler (ECCV 2024): LLM conclusions must be checked against explicit rules.
# - Holmes-VAD / ReCoVAD: expensive multimodal reasoning is only a candidate verifier;
#   the final system decision remains a controlled downstream step.
# - This file now implements validation-only finalization: the LLM policy layer
#   decides YES/NO/UNCERTAIN from Anomaly_Rules; Python validates consistency and
#   may downgrade unsafe/inconsistent outputs, but it never upgrades to YES.
POLICY_VERSION = "vad_reasoning_policy_v4_anomaly_rules_closed_world"

SEVERITY_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
RANK_SEVERITY = {v: k for k, v in SEVERITY_RANK.items()}

# If an LLM says YES, we still require a concrete, visible physical fact from the VLM.
# These words are not used to make an open-set decision; they only reject score-only or
# generic evidence before a matched Anomaly_Rules trigger can be applied.
_VISUAL_EVIDENCE_WORDS = frozenset({
    "person", "people", "subject", "body", "torso", "head", "arm", "arms", "hand", "hands",
    "leg", "legs", "knee", "knees", "foot", "feet", "limb", "posture", "floor", "ground",
    "lying", "prone", "sitting", "standing", "walking", "running", "sprinting", "stumbling",
    "fall", "falling", "collapsed", "collapse", "contact", "touching", "holding", "grabbing",
    "pushing", "shoving", "pulling", "hitting", "kicking", "grappling", "wrestling",
    "door", "window", "gate", "cabinet", "equipment", "machine", "panel", "object", "chair",
    "knife", "gun", "weapon", "fire", "smoke", "flame", "blocked", "covered", "camera",
})
_SCORE_EVIDENCE_WORDS = frozenset({
    "score", "threshold", "ratio", "embedding", "distance", "knn", "gmm", "percentile",
    "deviation", "model", "gate", "deep", "pose", "homography", "statistical",
})


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
    if decision == "NO":
        return "NONE"
    if decision == "UNCERTAIN" and severity in {"HIGH", "CRITICAL"}:
        return "MEDIUM"
    if decision == "YES" and severity == "NONE":
        return "LOW"
    return severity


def _evidence_items(vlm: VlmVisualReview) -> list[str]:
    # Internal schema still uses anomaly_evidence for compatibility, but the patched
    # VLM prompt now asks for rule_relevant_visual_facts. The parser maps that alias here.
    return [str(x).strip() for x in (vlm.anomaly_evidence or []) if str(x).strip()]


def _contains_visual_terms(text: str) -> bool:
    words = {w.strip(".,!?;:()[]{}\"'").lower() for w in text.split()}
    return bool(words & _VISUAL_EVIDENCE_WORDS)


def _is_score_only_text(text: str) -> bool:
    low = text.lower()
    has_score = any(term in low for term in _SCORE_EVIDENCE_WORDS)
    has_visual = _contains_visual_terms(low)
    return has_score and not has_visual


def _has_concrete_visual_evidence(vlm: VlmVisualReview) -> bool:
    items = _evidence_items(vlm)
    if not items:
        return False
    usable_items = [x for x in items if not _is_score_only_text(x)]
    if not usable_items:
        return False
    joined = " ".join(usable_items)
    return _contains_visual_terms(joined)


def _has_strong_normality(vlm: VlmVisualReview) -> bool:
    normal = " ".join(str(x) for x in (vlm.normality_evidence or [])).lower()
    return bool(normal and any(term in normal for term in [
        "walking", "standing", "sitting", "seated", "stationary", "normal pace",
        "ordinary", "routine", "working", "desk", "chair", "no contact", "no visible contact",
    ]))



def _applied_rules(rules: list[Any]) -> list[Any]:
    """Return LLM RuleApplication objects/dicts marked as applied."""
    out: list[Any] = []
    for rule in rules or []:
        applied = False
        if hasattr(rule, "applied"):
            applied = bool(getattr(rule, "applied"))
        elif isinstance(rule, dict):
            applied = bool(rule.get("applied"))
        if applied:
            out.append(rule)
    return out


def _rule_id(rule: Any) -> str:
    if hasattr(rule, "rule_id"):
        return str(getattr(rule, "rule_id"))
    if isinstance(rule, dict):
        return str(rule.get("rule_id") or rule.get("id") or "")
    return ""


def apply_python_final_guardrails(
    *,
    ctx: DeepReasoningContext | PoseReasoningContext,
    vlm: VlmVisualReview,
    llm: LlmPolicyReview,
    rules: list[dict[str, Any]],
    vlm_parse_info: dict[str, Any] | None = None,
    llm_parse_info: dict[str, Any] | None = None,
) -> tuple[PythonFinalResult, dict[str, Any]]:
    """Validation-only final layer.

    The VLM describes only. The LLM policy layer is the semantic decision-maker.
    Python validation cannot invent or upgrade a YES decision. It can only:
    - force UNCERTAIN on parse/schema failures,
    - downgrade inconsistent YES decisions,
    - normalize severity/action consistency,
    - report deterministic rule diagnostics for audit.
    """
    actions: list[dict[str, Any]] = []

    decision = str(llm.policy_alert_decision or "UNCERTAIN").upper()
    severity = str(llm.policy_severity or "LOW").upper()
    confidence = max(0.0, min(1.0, float(llm.policy_confidence or 0.3)))
    recommended_action = str(llm.recommended_action or "review_only")

    vlm_parse_error = (vlm_parse_info or {}).get("parse_error")
    llm_parse_error = (llm_parse_info or {}).get("parse_error")

    # Diagnostic only: deterministic matching is useful for audit, but it no longer
    # upgrades NO/UNCERTAIN to YES. The LLM is the only rule-decision layer.
    deterministic_rules = deterministic_rule_matches(ctx=ctx, vlm=vlm, rules=rules)
    deterministic_triggers = deterministic_rules.get("matched_trigger_rules", [])
    deterministic_suppress = deterministic_rules.get("matched_suppress_rules", [])

    llm_trigger_rules = _applied_rules(llm.matched_trigger_rules)
    llm_suppress_rules = _applied_rules(llm.matched_suppress_rules)
    concrete_visual = _has_concrete_visual_evidence(vlm)
    image_usable = vlm.image_quality not in {"UNUSABLE"}

    # 1) Parser failures are never allowed to become final alerts.
    if vlm_parse_error:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.30)
        actions.append({
            "rule_id": "VLM_PARSE_FALLBACK",
            "effect": "forced UNCERTAIN",
            "reason": str(vlm_parse_error),
        })
    if llm_parse_error:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.30)
        actions.append({
            "rule_id": "LLM_PARSE_FALLBACK",
            "effect": "forced UNCERTAIN",
            "reason": str(llm_parse_error),
        })

    # 2) The LLM must base its decision only on VLM-visible evidence.
    if not llm.evidence_assessment.uses_only_vlm_evidence:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.40)
        actions.append({
            "rule_id": "LLM_USED_NON_VLM_FACTS",
            "effect": "downgraded to UNCERTAIN",
            "reason": "The LLM indicated that it used information beyond the VLM visual observation.",
        })

    # 3) Validation-only closed-world rule: final YES requires the LLM to cite at
    # least one applied trigger rule. Python no longer creates YES by itself.
    if decision == "YES" and not llm_trigger_rules:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.45)
        actions.append({
            "rule_id": "YES_WITHOUT_LLM_TRIGGER_RULE",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": "Validation-only policy: final YES requires at least one LLM matched_trigger_rules entry with applied=true.",
        })

    # 4) Final YES also requires concrete visible facts and usable images. This is a
    # consistency check, not an independent anomaly judgement.
    if decision == "YES" and not concrete_visual:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.45)
        actions.append({
            "rule_id": "YES_WITHOUT_CONCRETE_VISUAL_FACTS",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": "A final YES requires concrete visible posture, motion, object, or interaction facts from the VLM observation.",
        })

    if decision == "YES" and not image_usable:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.40)
        actions.append({
            "rule_id": "YES_WITH_UNUSABLE_IMAGE_QUALITY",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": f"image_quality={vlm.image_quality}; visual evidence is not usable enough for final alert confirmation.",
        })

    # 5) Suppress rules are interpreted by the LLM. If the LLM explicitly matched a
    # suppress rule but still outputs YES, the safest validation result is UNCERTAIN.
    if decision == "YES" and llm_suppress_rules:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.50)
        actions.append({
            "rule_id": "YES_WITH_LLM_SUPPRESS_RULE",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": "The LLM matched a suppress rule while also returning YES; validation requires human review instead of direct alert.",
        })

    # 6) Score ratio is context only. It can cap confidence for weak evidence but
    # cannot create a YES and should not override a valid LLM NO.
    ratio = ctx.score_ratio
    if decision == "YES" and ratio is not None and ratio < 1.15:
        confidence = min(confidence, 0.70)
        actions.append({
            "rule_id": "WEAK_RATIO_CONFIDENCE_CAP",
            "effect": "kept LLM YES but capped confidence",
            "reason": f"score_ratio={ratio:.4f} is weak; score ratio is context only and cannot strengthen the decision.",
        })

    # 7) Severity/action normalization only.
    severity = _cap_severity_for_decision(decision, severity)
    normalized_action = _action_for(decision, severity)
    if not (decision in {"NO", "UNCERTAIN"} and recommended_action == "save_for_dataset"):
        if recommended_action != normalized_action:
            actions.append({
                "rule_id": "RECOMMENDED_ACTION_NORMALIZED",
                "effect": f"{recommended_action} -> {normalized_action}",
                "reason": "Recommended action must match final decision/severity.",
            })
        recommended_action = normalized_action

    base_reason = (llm.decision_reason or vlm.visual_decision_reason or "Final decision produced by LLM policy and validated by Python consistency checks.").strip()
    if actions:
        base_reason += " Python validation checked parse status, LLM rule references, visual grounding, image usability, suppress-rule consistency, and action/severity consistency."

    final = PythonFinalResult(
        final_alert_decision=decision,
        final_severity=severity,
        final_confidence=max(0.0, min(1.0, confidence)),
        final_recommended_action=recommended_action,
        final_decision_reason=base_reason,
        guardrail_actions=actions,
    )

    rules_result = {
        "rules_version": RULES_VERSION,
        "rule_source": "Anomaly_Rules",
        "decision_authority": "llm_policy_review",
        "python_role": "validation_only_no_yes_upgrade",
        "llm_matched_trigger_rules": [r.model_dump(mode="json") for r in llm.matched_trigger_rules],
        "llm_matched_suppress_rules": [r.model_dump(mode="json") for r in llm.matched_suppress_rules],
        "deterministic_matched_trigger_rules_diagnostic": deterministic_triggers,
        "deterministic_matched_suppress_rules_diagnostic": deterministic_suppress,
        "rule_reasoning": llm.rule_reasoning,
        "validation_notes": [a for a in actions],
    }
    return final, rules_result


def build_structured_result(
    *,
    ctx: DeepReasoningContext | PoseReasoningContext,
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
        f"{ctx.gate_name}_gate": {
            "peak_score": getattr(ctx, "deep_score", getattr(ctx, "pose_score", None)),
            "threshold_value": ctx.threshold_value,
            "score_ratio": ctx.score_ratio,
            "ratio_band": ctx.ratio_band(),
            "gate_decision": "candidate",
        },
        "vlm_visual_review": model_to_dict(vlm),
        "llm_policy_review": model_to_dict(llm),
        "python_final_guardrails": model_to_dict(final),  # backward-compatible key
        "python_validation_result": model_to_dict(final),
        "rule_evaluation": rules_result,
        "image_object_keys": image_object_keys,
        "raw_model_outputs": {
            "vlm": raw_vlm_output,
            "llm": raw_llm_output,
        },
        "parse_info": {
            "vlm": vlm_parse_info,
            "llm": llm_parse_info,
        },
        "policy_version": POLICY_VERSION,
    }
