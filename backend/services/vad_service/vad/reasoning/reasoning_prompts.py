from __future__ import annotations

import json
from typing import Any

from ..json_utils import sanitize_json
from .reasoning_schema import DeepReasoningContext, PoseReasoningContext, VlmVisualReview, model_to_dict


def _json(obj: Any, max_chars: int = 9000) -> str:
    text = json.dumps(sanitize_json(obj), ensure_ascii=False, indent=2, default=str, allow_nan=False)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...<truncated>"


def build_vlm_observation_hints(active_rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert active anomaly rules into a perception-only checklist for the VLM.

    The VLM must not apply trigger/suppress rules.  It receives only event-type
    names and descriptions as visual attention hints so it knows what kinds of
    motion/posture/person-object/person-person interactions must be described.
    Rule logic, severity, and final anomaly decisions remain in the LLM/Python
    cognition layers.
    """
    hints: list[dict[str, Any]] = []
    for rule in active_rules or []:
        if rule.get("active") is False:
            continue
        hints.append(
            {
                "rule_name": rule.get("rule_name") or rule.get("name") or "",
                "rule_type": rule.get("rule_type") or "",
                "visual_labels_to_watch": list(rule.get("event_types") or []),
                "description": rule.get("description") or "",
            }
        )
    return hints


def build_deep_vlm_visual_prompt(
    ctx: DeepReasoningContext,
    visual_observation_hints: list[dict[str, Any]] | None = None,
) -> str:
    return f"""
You are PHASE 2: VLM PERCEPTION in a decoupled Perception-to-Cognition video anomaly pipeline.

Architecture contract:
- You are an objective visual observer only.
- You must not apply anomaly rules.
- You must not make the final safety/security decision.
- You must not infer intent, guilt, policy violation, or danger beyond what is visible.
- The downstream text-only LLM will perform PHASE 3 cognition using your perception text plus JSON anomaly rules.
- Python guardrails will perform PHASE 4 final deterministic validation.

You are reviewing a candidate event produced by the Deep Visual Similarity Gate. The Deep gate compares VideoMAE-style visual embeddings against a normal memory bank. A score above threshold means the event is visually different from normal examples, but it does not prove that a real anomaly occurred.

Evidence package to inspect:
- Chronological raw tubelet frames are the primary evidence and may be the only images supplied.
- tubelet_montage.jpg and annotated_frame.jpg may be absent because small montage cells or overview annotations can be less legible for the VLM.
- If montage/annotated images are supplied, use them only as optional context; do not let them override the raw frame sequence.

Temporal inspection requirement:
Inspect every supplied frame as a motion sequence. Compare early, middle, and late frames before writing the motion description. Do not base the description only on the first frame, only on an overview image, or only on the largest/clearest single frame.

Perception-only checklist derived from active rules:
The following hints tell you what visual cues should be described if visible. They are NOT decision rules and must NOT be used to decide final anomaly status:
{_json(visual_observation_hints or [], 3500)}

Perception metadata:
{_json({
    "gate_name": ctx.gate_name,
    "event_id": ctx.event_id,
    "case_id": ctx.case_id,
    "tracker_track_id": ctx.tracker_track_id,
    "tubelet_id": ctx.tubelet_id,
    "stream_key": ctx.stream_key,
    "camera_key": ctx.camera_key,
}, 2200)}

Scene context:
{_json(ctx.scene_context, 2500)}

Do not mention gate scores, thresholds, ratios, embeddings, GMM/kNN distances, or statistical deviation in any VLM field. Those are not visual evidence and belong only to the downstream LLM cognition layer.

Images supplied in order:
{_json(ctx.evidence_object_keys, 1800)}

Return valid JSON only using the fields below. Do not copy the pipe-separated option text; choose one value for each enum field. The legacy field visual_alert_decision is only a perception flag:
- "YES" = you can see a concrete concerning visual cue that should be evaluated by the LLM rules
- "NO" = you see only ordinary/benign visual activity
- "UNCERTAIN" = the visual evidence is unclear, occluded, incomplete, or ambiguous

CRITICAL: Always include these four non-empty string fields: visible_scene, person_observation, motion_observation, visual_decision_reason.

{{
  "schema_version": "1.0",
  "review_type": "vlm_visual_review",
  "visual_alert_decision": "YES | NO | UNCERTAIN",
  "visual_severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "event_type": "normal_activity | benign_object_movement | benign_posture_change | camera_or_detection_artifact | unclear_visual_evidence | deep_semantic_spatiotemporal_anomaly | suspicious_motion | physical_altercation | fighting | pushing_or_shoving | grappling_or_wrestling | aggressive_contact | fall_or_collapse | unsafe_equipment_interaction | rapid_unusual_movement | person_on_floor | possible_intrusion_or_security_event",
  "visual_confidence": 0.0,
  "image_quality": "GOOD | FAIR | POOR | UNUSABLE",
  "evidence_sufficiency": "SUFFICIENT | PARTIAL | INSUFFICIENT",
  "visible_scene": "Objective global description of the laboratory scene and visible objects.",
  "person_observation": "Objective local description of visible people, target subject, body posture, proximity, contact, and interactions. Do not judge safety.",
  "motion_observation": "Objective step-by-step description of motion across early, middle, and late frames.",
  "anomaly_evidence": [
    "Only concrete visible cues that require LLM rule evaluation. Empty list if none."
  ],
  "normality_evidence": [
    "Concrete visible cues supporting ordinary or benign activity. Empty list if none."
  ],
  "false_positive_risks": [
    "Visual limitations such as occlusion, blur, perspective, detector drift, or ordinary activities that can mimic unusual motion."
  ],
  "visual_decision_reason": "Explain the perception flag using only visible evidence, without applying final anomaly rules."
}}

Constraints:
- Output JSON only.
- Do not output markdown.
- Do not output null values.
- Do not use score/threshold/ratio/statistical deviation as anomaly_evidence; describe only visible motion, posture, contact, objects, and scene cues.
- visual_confidence must be between 0.0 and 1.0.
- If visual_alert_decision is YES, anomaly_evidence must contain at least one concrete visible cue.
- Prefer a concrete visible event_type (for example fall_or_collapse, physical_altercation, normal_activity, suspicious_motion); do not use gate/model names as event_type unless no concrete visual category fits.
- If visual_alert_decision is NO, normality_evidence must contain at least one concrete visible reason.
- If visual_alert_decision is UNCERTAIN, explain the uncertainty.
""".strip()


def build_llm_policy_prompt(*, ctx: DeepReasoningContext | PoseReasoningContext, vlm_review: VlmVisualReview, active_rules: list[dict[str, Any]]) -> str:
    gate_context: dict[str, Any] = {
        "event_id": ctx.event_id,
        "case_id": ctx.case_id,
        "gate_name": ctx.gate_name,
        "score_ratio": ctx.score_ratio,
        "ratio_band": ctx.ratio_band(),
        "camera_id": ctx.camera_id,
        "stream_key": ctx.stream_key,
        "camera_key": ctx.camera_key,
        "tracker_track_id": ctx.tracker_track_id,
        "tubelet_id": ctx.tubelet_id,
        "threshold_value": ctx.threshold_value,
    }
    if getattr(ctx, "gate_name", "deep") == "pose":
        gate_context["pose_score"] = getattr(ctx, "pose_score", None)
        context_label = "Pose gate context:"
    else:
        gate_context["deep_score"] = getattr(ctx, "deep_score", None)
        context_label = "Deep gate context:"

    return f"""
You are PHASE 3: LLM COGNITION in a decoupled Perception-to-Cognition video anomaly pipeline.

Architecture contract:
- You did not see the images.
- You must not invent visual facts.
- The VLM was used only as the objective perception layer.
- Your primary job is to map the VLM perception text to the active JSON anomaly rules.
- The active rules are authoritative and preferred, but they are not the complete universe of possible anomalies.
- You may identify an open-set anomaly when the VLM perception text contains concrete visible evidence of a safety/security abnormality that is not covered by any active rule.
- Python guardrails will make the final deterministic validation after your output.

Inputs:
1. Gate metadata and score context.
2. Structured VLM perception JSON.
3. Active anomaly rules loaded from the rule engine/database.

Cognition procedure:
Step 1 — Shallow cognition:
- Compare the VLM's observed action against normal/benign rules, known false-positive rules, and trigger rules.
- Decide whether a rule is violated or whether a suppress/benign rule applies.
- If no trigger rule covers the observed action, evaluate whether the visible facts describe an open-set laboratory anomaly: an action that is plainly unsafe, threatening, destructive, incapacitating, security-relevant, or operationally abnormal even though it is not explicitly listed in the active rules.

Step 2 — Deep cognition:
- If a violation is supported by the VLM perception text and matched rules, assess severity and consequence in a laboratory environment.
- If an open-set anomaly is supported by concrete VLM facts but no explicit trigger rule matches, assess it conservatively and label the trigger as OPEN_SET_VISUAL_ANOMALY in matched_trigger_rules.
- If evidence is occluded, ambiguous, or insufficient, choose UNCERTAIN or NO according to the rules.

Important constraints:
1. Use only visual facts present in the VLM review.
2. Do not add new visual facts.
3. Score ratio alone is never enough for YES.
4. A weak score ratio should make borderline/ambiguous cases conservative.
5. A trigger rule may be applied only if the VLM provides concrete visual evidence matching that rule.
6. Open-set anomaly reasoning is allowed only when the VLM provides concrete visual evidence of a laboratory-relevant abnormal event that is not covered by the active trigger rules.
7. Do not use open-set reasoning for vague unusualness, score/threshold deviation, ordinary walking, sitting, standing, chair movement, normal posture changes, partial occlusion, detector drift, or weak/ambiguous cues.
8. A suppress rule may be applied when the VLM text matches normal, benign, false-positive, unclear, or artifact conditions.
9. If trigger/open-set and suppress rules appear to conflict, explain the conflict and choose the more conservative decision unless the VLM evidence clearly supports the trigger/open-set anomaly.
10. Output valid JSON only.

{context_label}
{_json(gate_context, 2500)}

VLM perception review:
{_json(model_to_dict(vlm_review), 6500)}

Active anomaly rules:
{_json(active_rules, 9000)}

Policy labels:
- YES means visually supported safety/security anomaly after rule mapping, or a clearly supported open-set laboratory anomaly when no explicit rule covers it.
- NO means normal or benign event.
- UNCERTAIN means weak, ambiguous, incomplete, or insufficient evidence.
- recommended_action must align with the decision and severity.

Return exactly this JSON:

{{
  "schema_version": "1.0",
  "review_type": "llm_policy_review",
  "policy_alert_decision": "YES | NO | UNCERTAIN",
  "policy_severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "policy_confidence": 0.0,
  "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
  "score_assessment": {{
    "score_ratio": 0.0,
    "ratio_band": "weak | moderate | strong",
    "score_reasoning": "Explain how the score ratio affects the rule-based cognition."
  }},
  "matched_trigger_rules": [
    {{
      "rule_id": "... or OPEN_SET_VISUAL_ANOMALY",
      "rule_name": "... or Open-set visually supported laboratory anomaly",
      "applied": true,
      "reason": "For explicit rules, explain the active rule match. For OPEN_SET_VISUAL_ANOMALY, explain why the visible facts are plainly anomalous even though no active rule covered them."
    }}
  ],
  "matched_suppress_rules": [
    {{
      "rule_id": "...",
      "rule_name": "...",
      "applied": true,
      "reason": "..."
    }}
  ],
  "rule_reasoning": [
    "Explain how active rules were mapped to the VLM perception text."
  ],
  "evidence_assessment": {{
    "uses_only_vlm_evidence": true,
    "has_strong_visual_anomaly_evidence": true,
    "has_normality_evidence": true,
    "has_false_positive_risk": true
  }},
  "decision_reason": "Explain the final policy decision using only gate context, VLM perception, active rules, and if needed conservative open-set anomaly reasoning.",
  "limitations": [
    "Mention ambiguity, occlusion, weak score ratio, or missing evidence if relevant."
  ]
}}

Constraints:
- policy_confidence must be between 0.0 and 1.0.
- If policy_alert_decision is YES, at least one explicit trigger rule OR OPEN_SET_VISUAL_ANOMALY must be listed and concrete VLM evidence must support it.
- If no explicit rule clearly supports YES but the visible facts are plainly unsafe/security-relevant/operationally abnormal, use OPEN_SET_VISUAL_ANOMALY conservatively.
- If neither an explicit rule nor a concrete open-set anomaly supports YES, choose NO or UNCERTAIN.
- Output JSON only.
""".strip()


def build_pose_vlm_visual_prompt(
    ctx: PoseReasoningContext,
    visual_observation_hints: list[dict[str, Any]] | None = None,
) -> str:
    return f"""
You are PHASE 2: VLM PERCEPTION in a decoupled Perception-to-Cognition video anomaly pipeline.

Architecture contract:
- You are an objective visual observer only.
- You must not apply anomaly rules.
- You must not make the final safety/security decision.
- You must not infer intent, guilt, policy violation, or danger beyond what is visible.
- The downstream text-only LLM will perform PHASE 3 cognition using your perception text plus JSON anomaly rules.
- Python guardrails will perform PHASE 4 final deterministic validation.

You are reviewing a candidate event produced by the Pose Micro-Motion Gate. The Pose gate detects unusual keypoint/postural dynamics. A score above threshold means the pose sequence is statistically unusual, but it does not prove that a real anomaly occurred.

Evidence package to inspect:
- Chronological raw pose/tubelet frames are the primary evidence and may be the only images supplied.
- keypoint/skeleton montage and annotated_frame.jpg may be absent because small montage cells or overview annotations can be less legible for the VLM.
- If montage/annotated images are supplied, use them only as optional context; prioritize the raw frame sequence.

Temporal inspection requirement:
Inspect every supplied frame as a motion sequence. Compare early, middle, and late frames before describing posture and articulation. Describe hands, torso angle, limb positions, collapse/stumble patterns, proximity/contact, and object interaction only when visible.

Perception-only checklist derived from active rules:
The following hints tell you what visual cues should be described if visible. They are NOT decision rules and must NOT be used to decide final anomaly status:
{_json(visual_observation_hints or [], 3500)}

Perception metadata:
{_json({
    "gate_name": ctx.gate_name,
    "event_id": ctx.event_id,
    "case_id": ctx.case_id,
    "tracker_track_id": ctx.tracker_track_id,
    "tubelet_id": ctx.tubelet_id,
    "stream_key": ctx.stream_key,
    "camera_key": ctx.camera_key,
}, 2200)}

Scene context:
{_json(ctx.scene_context, 2500)}

Do not mention pose score, thresholds, ratios, keypoint model internals, GMM distance, or statistical deviation in any VLM field. Those are not visual evidence and belong only to the downstream LLM cognition layer.

Images supplied in order:
{_json(ctx.evidence_object_keys, 1800)}

Return valid JSON only using the same fields used by the Deep VLM perception stage. Do not copy the pipe-separated option text; choose one value for each enum field. The legacy field visual_alert_decision is only a perception flag:
- "YES" = you can see a concrete concerning visual cue that should be evaluated by the LLM rules
- "NO" = you see only ordinary/benign visual activity
- "UNCERTAIN" = the visual evidence is unclear, occluded, incomplete, or ambiguous

CRITICAL: Always include these four non-empty string fields: visible_scene, person_observation, motion_observation, visual_decision_reason.

{{
  "schema_version": "1.0",
  "review_type": "vlm_visual_review",
  "visual_alert_decision": "YES | NO | UNCERTAIN",
  "visual_severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "event_type": "normal_activity | benign_object_movement | benign_posture_change | camera_or_detection_artifact | unclear_visual_evidence | deep_semantic_spatiotemporal_anomaly | suspicious_motion | physical_altercation | fighting | pushing_or_shoving | grappling_or_wrestling | aggressive_contact | fall_or_collapse | unsafe_equipment_interaction | rapid_unusual_movement | person_on_floor | possible_intrusion_or_security_event",
  "visual_confidence": 0.0,
  "image_quality": "GOOD | FAIR | POOR | UNUSABLE",
  "evidence_sufficiency": "SUFFICIENT | PARTIAL | INSUFFICIENT",
  "visible_scene": "Objective global description of the laboratory scene and visible objects.",
  "person_observation": "Objective local description of visible people, target subject, body posture, proximity, contact, and interactions. Do not judge safety.",
  "motion_observation": "Objective step-by-step description of posture/motion across early, middle, and late frames.",
  "anomaly_evidence": [
    "Only concrete visible cues that require LLM rule evaluation. Empty list if none."
  ],
  "normality_evidence": [
    "Concrete visible cues supporting ordinary or benign activity. Empty list if none."
  ],
  "false_positive_risks": [
    "Visual limitations or benign posture changes that can mimic abnormal pose."
  ],
  "visual_decision_reason": "Explain the perception flag using only visible evidence, without applying final anomaly rules."
}}

Constraints:
- Output JSON only.
- Do not output markdown.
- Do not output null values.
- Do not use score/threshold/ratio/statistical deviation as anomaly_evidence; describe only visible motion, posture, contact, objects, and scene cues.
- visual_confidence must be between 0.0 and 1.0.
- If visual_alert_decision is YES, anomaly_evidence must contain at least one concrete visible cue.
- Prefer a concrete visible event_type (for example fall_or_collapse, physical_altercation, normal_activity, suspicious_motion); do not use gate/model names as event_type unless no concrete visual category fits.
- If visual_alert_decision is NO, normality_evidence must contain at least one concrete visible reason.
- If visual_alert_decision is UNCERTAIN, explain the uncertainty.
""".strip()
