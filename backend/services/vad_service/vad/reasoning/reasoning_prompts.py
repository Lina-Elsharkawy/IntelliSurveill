from __future__ import annotations

import json
from typing import Any

from .reasoning_schema import DeepReasoningContext, VlmVisualReview, model_to_dict


def _json(obj: Any, max_chars: int = 9000) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...<truncated>"


def build_deep_vlm_visual_prompt(ctx: DeepReasoningContext) -> str:
    return f"""
You are a visual reviewer for a backend Video Anomaly Detection system.

You are reviewing a candidate event produced by the Deep Visual Similarity Gate. The Deep gate compares VideoMAE-style visual embeddings against a normal memory bank. A score above threshold means the event is visually different from normal examples, but it does not prove that a real anomaly occurred.

Your task is to inspect only the provided visual evidence:
- annotated_frame.jpg
- tubelet_montage.jpg
- selected tubelet frames if provided

You must describe what is visible and produce a structured visual review.

Important rules:
1. You are not the final system decision-maker.
2. The Deep score is not ground truth.
3. Do not blindly confirm the Deep gate.
4. Use only visible evidence.
5. Do not infer intent.
6. Do not invent unseen actions.
7. Do not claim a fall, collapse, intrusion, unsafe interaction, or suspicious event unless it is visually supported.
8. If the person is standing, sitting, walking, turning, or making a normal posture change, say so.
9. If the evidence is blurry, occluded, incomplete, or ambiguous, choose UNCERTAIN.
10. If visual evidence appears normal or benign, choose NO.
11. YES requires concrete visible anomaly evidence.
12. Do not leave explanation fields empty.
13. Output only valid JSON. No markdown. No prose outside JSON.

Deep score context:
- deep_score: {ctx.deep_score}
- threshold_value: {ctx.threshold_value}
- score_ratio: {ctx.score_ratio}

Score interpretation:
- score_ratio close to 1.0 means the Deep gate is only slightly above threshold.
- If score_ratio < 1.15, treat the Deep signal as weak.
- A weak score should not be treated as visual proof of anomaly.

Event metadata:
{_json(ctx.event_metadata, 3500)}

Deep gate metadata:
{_json(ctx.deep_gate_metadata, 3500)}

Scene context:
{_json(ctx.scene_context, 2500)}

Images supplied in order:
{_json(ctx.evidence_object_keys, 1200)}

Return exactly this JSON:

{{
  "schema_version": "1.0",
  "review_type": "vlm_visual_review",
  "visual_alert_decision": "YES | NO | UNCERTAIN",
  "visual_severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "event_type": "normal_activity | benign_object_movement | benign_posture_change | camera_or_detection_artifact | unclear_visual_evidence | deep_semantic_spatiotemporal_anomaly | suspicious_motion | fall_or_collapse | unsafe_equipment_interaction | rapid_unusual_movement | person_on_floor | possible_intrusion_or_security_event",
  "visual_confidence": 0.0,
  "image_quality": "GOOD | FAIR | POOR | UNUSABLE",
  "evidence_sufficiency": "SUFFICIENT | PARTIAL | INSUFFICIENT",
  "visible_scene": "Describe only what is visible.",
  "person_observation": "Describe visible person/body/posture/action only.",
  "motion_observation": "Describe visible motion/change across the montage. If unclear, say so.",
  "anomaly_evidence": [
    "Concrete visible evidence supporting anomaly, if any."
  ],
  "normality_evidence": [
    "Concrete visible evidence supporting normal or benign interpretation, if any."
  ],
  "false_positive_risks": [
    "Reasons the Deep event may be a false positive, if any."
  ],
  "visual_decision_reason": "Explain the visual decision based only on visible evidence."
}}

Constraints:
- visual_confidence must be between 0.0 and 1.0.
- If visual_alert_decision is YES, anomaly_evidence must contain at least one concrete visible anomaly.
- If visual_alert_decision is NO, normality_evidence must contain at least one concrete visible reason.
- If visual_alert_decision is UNCERTAIN, explain the uncertainty in false_positive_risks or evidence_sufficiency.
- Do not output null values.
- Output JSON only.
""".strip()


def build_llm_policy_prompt(*, ctx: DeepReasoningContext, vlm_review: VlmVisualReview, active_rules: list[dict[str, Any]]) -> str:
    deep_context = {
        "event_id": ctx.event_id,
        "case_id": ctx.case_id,
        "gate_name": ctx.gate_name,
        "deep_score": ctx.deep_score,
        "threshold_value": ctx.threshold_value,
        "score_ratio": ctx.score_ratio,
        "ratio_band": ctx.ratio_band(),
        "camera_id": ctx.camera_id,
        "stream_key": ctx.stream_key,
        "camera_key": ctx.camera_key,
        "tracker_track_id": ctx.tracker_track_id,
        "tubelet_id": ctx.tubelet_id,
    }
    return f"""
You are the policy and anomaly-rules reasoning layer for a backend Video Anomaly Detection system.

You did not see the images.
You must not invent visual facts.
You must rely only on the structured VLM visual review provided below.

The Deep gate is a candidate detector, not ground truth.
The VLM is the visual evidence extractor.
Your job is to combine:
- Deep score context
- VLM visual review
- anomaly trigger/suppress rules
- system policy

Then produce a structured policy decision.

Important rules:
1. You may reinterpret the decision, but you may not reinterpret the image.
2. You may not add visual evidence that is not present in the VLM review.
3. You may downgrade a VLM YES to UNCERTAIN or NO if evidence is weak.
4. You may escalate only when the VLM provides concrete anomaly evidence.
5. You may not convert NO or UNCERTAIN to YES unless the VLM review contains strong visual anomaly evidence.
6. If score_ratio < 1.15, be conservative.
7. If VLM anomaly_evidence is empty or only score-based, do not choose YES.
8. If VLM image_quality is POOR or UNUSABLE, do not choose YES unless the VLM clearly reports a visible severe anomaly.
9. Apply suppress rules before trigger rules.
10. Trigger rules cannot invent anomalies.
11. Suppress rules may downgrade normal/benign/unclear events.
12. Output only valid JSON. No markdown. No prose outside JSON.

Deep context:
{_json(deep_context, 2500)}

VLM visual review:
{_json(model_to_dict(vlm_review), 6500)}

Active anomaly rules:
{_json(active_rules, 6500)}

Policy:
- YES means visually supported safety/security anomaly.
- NO means normal or benign event.
- UNCERTAIN means weak, ambiguous, incomplete, or insufficient evidence.
- Weak score ratio: score_ratio < 1.15.
- Moderate score ratio: 1.15 <= score_ratio < 1.50.
- Strong score ratio: score_ratio >= 1.50.
- Score ratio alone is never enough for YES.

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
    "score_reasoning": "Explain how the score ratio affects the decision."
  }},
  "matched_trigger_rules": [
    {{
      "rule_id": "...",
      "rule_name": "...",
      "applied": true,
      "reason": "..."
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
    "Explain how rules affected or did not affect the decision."
  ],
  "evidence_assessment": {{
    "uses_only_vlm_evidence": true,
    "has_strong_visual_anomaly_evidence": true,
    "has_normality_evidence": true,
    "has_false_positive_risk": true
  }},
  "decision_reason": "Explain the final policy decision using only Deep context, VLM review, and rules.",
  "limitations": [
    "Mention ambiguity or missing evidence, if any."
  ]
}}

Constraints:
- policy_confidence must be between 0.0 and 1.0.
- If policy_alert_decision is YES, has_strong_visual_anomaly_evidence must be true.
- If policy_alert_decision is YES, VLM anomaly_evidence must contain concrete visual evidence.
- If policy_alert_decision is NO, explain why the event is normal/benign or suppressed.
- If policy_alert_decision is UNCERTAIN, explain what prevents confirmation.
- Do not output null values.
- Output JSON only.
""".strip()
