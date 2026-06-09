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
# - This file deliberately implements a closed-world policy: only active Anomaly_Rules
#   can confirm a YES. The LLM may propose; Python verifies deterministically.
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


def apply_python_final_guardrails(
    *,
    ctx: DeepReasoningContext | PoseReasoningContext,
    vlm: VlmVisualReview,
    llm: LlmPolicyReview,
    rules: list[dict[str, Any]],
    vlm_parse_info: dict[str, Any] | None = None,
    llm_parse_info: dict[str, Any] | None = None,
) -> tuple[PythonFinalResult, dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    decision = str(llm.policy_alert_decision or "UNCERTAIN")
    severity = str(llm.policy_severity or "LOW")
    confidence = max(0.0, min(1.0, float(llm.policy_confidence or 0.3)))
    recommended_action = str(llm.recommended_action or "review_only")

    # 1) Parser failures are never allowed to become alerts.
    vlm_parse_error = (vlm_parse_info or {}).get("parse_error")
    llm_parse_error = (llm_parse_info or {}).get("parse_error")
    if vlm_parse_error:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.30)
        actions.append({"rule_id": "VLM_PARSE_FALLBACK", "effect": "forced UNCERTAIN", "reason": str(vlm_parse_error)})
    if llm_parse_error:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.30)
        actions.append({"rule_id": "LLM_PARSE_FALLBACK", "effect": "forced UNCERTAIN", "reason": str(llm_parse_error)})

    # 2) Closed-world rule matching from the single source of truth: Anomaly_Rules.
    deterministic_rules = deterministic_rule_matches(ctx=ctx, vlm=vlm, rules=rules)
    matched_triggers = deterministic_rules.get("matched_trigger_rules", [])
    matched_suppress = deterministic_rules.get("matched_suppress_rules", [])

    concrete_visual = _has_concrete_visual_evidence(vlm)
    image_usable = vlm.image_quality not in {"UNUSABLE"}
    strong_normality = _has_strong_normality(vlm)
    ratio = ctx.score_ratio

    # 3) LLM must not invent visual facts beyond VLM caption.
    if not llm.evidence_assessment.uses_only_vlm_evidence:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.40)
        actions.append({
            "rule_id": "LLM_USED_NON_VLM_FACTS",
            "effect": "downgraded to UNCERTAIN",
            "reason": "The LLM admitted it used information beyond VLM-visible evidence.",
        })

    # 4) Suppress rules can force NO, unless there is a concrete trigger match.
    #    Important: do not apply suppress rules to parser-fallback/unclear evidence
    #    merely because a broad admin rule uses event_type='other'. Suppression must
    #    be grounded in concrete normality or concrete visual facts.
    suppress_grounded = (not vlm_parse_error) and (strong_normality or concrete_visual or bool(vlm.normality_evidence))
    if matched_suppress and suppress_grounded and not (matched_triggers and concrete_visual):
        decision, severity, recommended_action = "NO", "NONE", "ignore"
        confidence = min(max(confidence, 0.60), 0.85)
        for rule in matched_suppress:
            actions.append({
                "rule_id": rule.get("rule_id"),
                "effect": "applied suppress rule",
                "reason": rule.get("reason") or "Active Anomaly_Rules suppress rule matched grounded normal/benign VLM caption.",
            })
    elif matched_suppress and not suppress_grounded:
        actions.append({
            "rule_id": "SUPPRESS_NOT_APPLIED_WITHOUT_GROUNDING",
            "effect": "ignored ungrounded suppress match",
            "reason": "A suppress rule matched broad metadata/event_type, but VLM perception was parse-fallback or lacked concrete normality/visual grounding.",
        })

    # 5) Hard closed-world guardrail: YES is only possible with an active trigger rule
    #    AND concrete visual evidence. Score ratio alone cannot create YES.
    if decision == "YES" and not matched_triggers:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.45)
        actions.append({
            "rule_id": "YES_WITHOUT_ANOMALY_RULE_TRIGGER",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": "Closed-world policy: no active Anomaly_Rules trigger matched the VLM-visible facts.",
        })

    if decision == "YES" and not concrete_visual:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.45)
        actions.append({
            "rule_id": "YES_WITHOUT_CONCRETE_VISUAL_FACTS",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": "A final YES requires concrete visible posture, motion, object, or interaction evidence, not scores or generic labels.",
        })

    if decision == "YES" and not image_usable:
        decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
        confidence = min(confidence, 0.40)
        actions.append({
            "rule_id": "YES_WITH_UNUSABLE_IMAGE_QUALITY",
            "effect": "downgraded YES to UNCERTAIN",
            "reason": f"image_quality={vlm.image_quality}; visual evidence is not usable enough for a final alert.",
        })

    # 6) Conservative score-ratio guardrail. Weak ratios do not block explicit high-risk
    #    admin rules, but they reduce confidence and force review unless the rule minimum
    #    severity is HIGH/CRITICAL or the VLM evidence is very concrete.
    if decision == "YES" and ratio is not None and ratio < 1.15:
        high_risk_rule = any(
            SEVERITY_RANK.get(str((r.get("effect") or {}).get("minimum_severity") or "MEDIUM"), 2) >= SEVERITY_RANK["HIGH"]
            for r in matched_triggers
        )
        if not high_risk_rule:
            decision, severity, recommended_action = "UNCERTAIN", "LOW", "review_only"
            confidence = min(confidence, 0.50)
            actions.append({
                "rule_id": "WEAK_RATIO_REQUIRES_HIGH_RISK_RULE",
                "effect": "downgraded YES to UNCERTAIN",
                "reason": f"score_ratio={ratio:.4f} is weak and no HIGH/CRITICAL active Anomaly_Rules trigger matched.",
            })
        else:
            confidence = min(confidence, 0.70)
            actions.append({
                "rule_id": "WEAK_RATIO_HIGH_RISK_REVIEW",
                "effect": "kept YES with capped confidence",
                "reason": f"score_ratio={ratio:.4f} is weak, but a HIGH/CRITICAL active rule matched concrete visual evidence.",
            })

    # 7) If Python finds a trigger and VLM visual facts are concrete, it can upgrade an
    #    LLM UNCERTAIN/NO to YES. This is the deterministic rule layer doing its job.
    if decision != "YES" and matched_triggers and concrete_visual and image_usable and not strong_normality:
        for rule in matched_triggers:
            effect = rule.get("effect") or {}
            min_sev = str(effect.get("minimum_severity") or "MEDIUM")
            decision = "YES"
            severity = _min_severity(severity, min_sev)
            recommended_action = str(effect.get("recommended_action") or _action_for(decision, severity))
            confidence = max(confidence, min(0.85, float(vlm.visual_confidence or 0.5)))
            actions.append({
                "rule_id": rule.get("rule_id"),
                "effect": "upgraded to YES by deterministic rule",
                "reason": rule.get("reason") or "Active Anomaly_Rules trigger matched concrete VLM-visible facts.",
            })

    # 8) Strong normality evidence prevents accidental escalation unless an explicit trigger
    #    rule has already survived all checks above.
    if decision == "YES" and strong_normality and not matched_triggers:
        decision, severity, recommended_action = "NO", "NONE", "ignore"
        confidence = min(confidence, 0.70)
        actions.append({
            "rule_id": "NORMALITY_WITHOUT_TRIGGER",
            "effect": "forced NO",
            "reason": "VLM described ordinary activity and no explicit trigger rule matched.",
        })

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

    base_reason = (llm.decision_reason or vlm.visual_decision_reason or "Final decision produced by deterministic guardrails.").strip()
    if actions:
        base_reason += " Python guardrails enforced closed-world Anomaly_Rules matching, concrete VLM-visible facts, score-ratio checks, and suppress-rule precedence."

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
        "llm_matched_trigger_rules": [r.model_dump(mode="json") for r in llm.matched_trigger_rules],
        "llm_matched_suppress_rules": [r.model_dump(mode="json") for r in llm.matched_suppress_rules],
        "deterministic_matched_trigger_rules": matched_triggers,
        "deterministic_matched_suppress_rules": matched_suppress,
        "rule_reasoning": llm.rule_reasoning,
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
        "python_final_guardrails": model_to_dict(final),
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
