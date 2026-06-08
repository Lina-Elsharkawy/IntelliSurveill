from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ALERT_DECISIONS = {"YES", "NO", "UNCERTAIN"}
SEVERITIES = {"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
EVENT_TYPES = {
    "normal_activity",
    "benign_object_movement",
    "benign_posture_change",
    "camera_or_detection_artifact",
    "unclear_visual_evidence",
    "deep_semantic_spatiotemporal_anomaly",
    "suspicious_motion",
    "fall_or_collapse",
    "unsafe_equipment_interaction",
    "rapid_unusual_movement",
    "person_on_floor",
    "possible_intrusion_or_security_event",
}
IMAGE_QUALITIES = {"GOOD", "FAIR", "POOR", "UNUSABLE"}
EVIDENCE_SUFFICIENCIES = {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"}
ACTIONS = {"ignore", "review_only", "save_for_dataset", "alert_operator", "urgent_alert"}
RATIO_BANDS = {"weak", "moderate", "strong"}


class DeepReasoningContext(BaseModel):
    event_id: int | None = None
    case_id: int | None = None
    gate_name: str = "deep"
    deep_score: float | None = None
    threshold_value: float | None = None
    score_ratio: float | None = None
    camera_id: int | None = None
    stream_key: str | None = None
    camera_key: str | None = None
    tracker_track_id: int | None = None
    tubelet_id: int | None = None
    evidence_object_keys: list[str] = Field(default_factory=list)
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    deep_gate_metadata: dict[str, Any] = Field(default_factory=dict)
    scene_context: dict[str, Any] = Field(default_factory=dict)

    def ratio_band(self) -> str:
        ratio = self.score_ratio
        if ratio is None:
            return "weak"
        if ratio < 1.15:
            return "weak"
        if ratio < 1.50:
            return "moderate"
        return "strong"
class PoseReasoningContext(BaseModel):
    event_id: int | None = None
    case_id: int | None = None
    gate_name: str = "pose"
    pose_score: float | None = None
    threshold_value: float | None = None
    score_ratio: float | None = None
    camera_id: int | None = None
    stream_key: str | None = None
    camera_key: str | None = None
    tracker_track_id: int | None = None
    tubelet_id: int | None = None
    evidence_object_keys: list[str] = Field(default_factory=list)
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    pose_gate_metadata: dict[str, Any] = Field(default_factory=dict)
    scene_context: dict[str, Any] = Field(default_factory=dict)

    def ratio_band(self) -> str:
        ratio = self.score_ratio
        if ratio is None:
            return "weak"
        if ratio < 1.15:
            return "weak"
        if ratio < 1.50:
            return "moderate"
        return "strong"

class VlmVisualReview(BaseModel):
    schema_version: str = "1.0"
    review_type: Literal["vlm_visual_review"] = "vlm_visual_review"
    visual_alert_decision: Literal["YES", "NO", "UNCERTAIN"] = "UNCERTAIN"
    visual_severity: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    event_type: Literal[
        "normal_activity",
        "benign_object_movement",
        "benign_posture_change",
        "camera_or_detection_artifact",
        "unclear_visual_evidence",
        "deep_semantic_spatiotemporal_anomaly",
        "suspicious_motion",
        "fall_or_collapse",
        "unsafe_equipment_interaction",
        "rapid_unusual_movement",
        "person_on_floor",
        "possible_intrusion_or_security_event",
    ] = "unclear_visual_evidence"
    visual_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    image_quality: Literal["GOOD", "FAIR", "POOR", "UNUSABLE"] = "FAIR"
    evidence_sufficiency: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"] = "PARTIAL"
    visible_scene: str
    person_observation: str
    motion_observation: str
    anomaly_evidence: list[str] = Field(default_factory=list)
    normality_evidence: list[str] = Field(default_factory=list)
    false_positive_risks: list[str] = Field(default_factory=list)
    visual_decision_reason: str

    @field_validator("visible_scene", "person_observation", "motion_observation", "visual_decision_reason")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("anomaly_evidence", "normality_evidence", "false_positive_risks", mode="before")
    @classmethod
    def listify(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        text = str(value).strip()
        return [text] if text else []


class RuleApplication(BaseModel):
    rule_id: str
    rule_name: str | None = None
    applied: bool = False
    reason: str = ""


class ScoreAssessment(BaseModel):
    score_ratio: float | None = None
    ratio_band: Literal["weak", "moderate", "strong"] = "weak"
    score_reasoning: str = ""


class EvidenceAssessment(BaseModel):
    uses_only_vlm_evidence: bool = True
    has_strong_visual_anomaly_evidence: bool = False
    has_normality_evidence: bool = False
    has_false_positive_risk: bool = False


class LlmPolicyReview(BaseModel):
    schema_version: str = "1.0"
    review_type: Literal["llm_policy_review"] = "llm_policy_review"
    policy_alert_decision: Literal["YES", "NO", "UNCERTAIN"] = "UNCERTAIN"
    policy_severity: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    policy_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    recommended_action: Literal["ignore", "review_only", "save_for_dataset", "alert_operator", "urgent_alert"] = "review_only"
    score_assessment: ScoreAssessment = Field(default_factory=ScoreAssessment)
    matched_trigger_rules: list[RuleApplication] = Field(default_factory=list)
    matched_suppress_rules: list[RuleApplication] = Field(default_factory=list)
    rule_reasoning: list[str] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessment = Field(default_factory=EvidenceAssessment)
    decision_reason: str = ""
    limitations: list[str] = Field(default_factory=list)

    @field_validator("matched_trigger_rules", "matched_suppress_rules", "rule_reasoning", "limitations", mode="before")
    @classmethod
    def listify(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        text = str(value).strip()
        return [text] if text else []

    @field_validator("decision_reason")
    @classmethod
    def non_empty_reason(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("decision_reason must not be empty")
        return value


class PythonFinalResult(BaseModel):
    schema_version: str = "1.0"
    review_type: Literal["python_final_guardrails"] = "python_final_guardrails"
    final_alert_decision: Literal["YES", "NO", "UNCERTAIN"] = "UNCERTAIN"
    final_severity: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    final_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    final_recommended_action: Literal["ignore", "review_only", "save_for_dataset", "alert_operator", "urgent_alert"] = "review_only"
    final_decision_reason: str
    guardrail_actions: list[dict[str, Any]] = Field(default_factory=list)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract first JSON object from a possibly chatty/fenced model response."""
    text = (text or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _upper_allowed(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().upper()
    return text if text in allowed else default


def _lower_allowed(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _confidence(value: Any, default: float = 0.3) -> float:
    try:
        out = float(value)
        if out != out:
            return default
        return max(0.0, min(1.0, out))
    except Exception:
        return default


def fallback_vlm_uncertain(reason: str) -> VlmVisualReview:
    reason = str(reason or "VLM visual review unavailable").strip()
    return VlmVisualReview(
        visual_alert_decision="UNCERTAIN",
        visual_severity="LOW",
        event_type="unclear_visual_evidence",
        visual_confidence=0.25,
        image_quality="FAIR",
        evidence_sufficiency="INSUFFICIENT",
        visible_scene="The visual scene could not be reliably structured by the VLM.",
        person_observation="The person observation is unavailable or incomplete.",
        motion_observation="The motion observation is unavailable or incomplete.",
        anomaly_evidence=[],
        normality_evidence=[],
        false_positive_risks=[reason],
        visual_decision_reason=reason,
    )


def fallback_llm_uncertain(reason: str, *, ctx: DeepReasoningContext | PoseReasoningContext | None = None, vlm: VlmVisualReview | None = None) -> LlmPolicyReview:
    ratio = ctx.score_ratio if ctx else None
    has_norm = bool(vlm and vlm.normality_evidence)
    has_fp = bool(vlm and vlm.false_positive_risks)
    return LlmPolicyReview(
        policy_alert_decision="UNCERTAIN",
        policy_severity="LOW",
        policy_confidence=0.30,
        recommended_action="review_only",
        score_assessment=ScoreAssessment(
            score_ratio=ratio,
            ratio_band=ctx.ratio_band() if ctx else "weak",
            score_reasoning="LLM policy review failed or was unavailable, so score context is treated conservatively.",
        ),
        matched_trigger_rules=[],
        matched_suppress_rules=[],
        rule_reasoning=["No LLM rule reasoning was available."],
        evidence_assessment=EvidenceAssessment(
            uses_only_vlm_evidence=True,
            has_strong_visual_anomaly_evidence=False,
            has_normality_evidence=has_norm,
            has_false_positive_risk=has_fp,
        ),
        decision_reason=reason or "LLM policy review unavailable; defaulting to UNCERTAIN.",
        limitations=[reason or "LLM policy review unavailable"],
    )


def parse_vlm_visual_review(raw_text: str) -> tuple[VlmVisualReview, dict[str, Any]]:
    raw = extract_json_object(raw_text)
    if not raw:
        return fallback_vlm_uncertain("VLM did not return parseable JSON."), {"parse_error": "empty_or_invalid_json"}

    # Backward-compatible alias normalization for earlier shallow outputs.
    if "visual_alert_decision" not in raw and "alert_decision" in raw:
        raw["visual_alert_decision"] = _upper_allowed(raw.get("alert_decision"), ALERT_DECISIONS, "UNCERTAIN")
    if "visual_severity" not in raw and "severity" in raw:
        raw["visual_severity"] = _upper_allowed(raw.get("severity"), SEVERITIES, "LOW")
    if "visual_confidence" not in raw and "confidence" in raw:
        raw["visual_confidence"] = _confidence(raw.get("confidence"), 0.3)
    raw["review_type"] = "vlm_visual_review"
    raw["schema_version"] = str(raw.get("schema_version") or "1.0")
    raw["visual_alert_decision"] = _upper_allowed(raw.get("visual_alert_decision"), ALERT_DECISIONS, "UNCERTAIN")
    raw["visual_severity"] = _upper_allowed(raw.get("visual_severity"), SEVERITIES, "LOW")
    raw["event_type"] = _lower_allowed(raw.get("event_type"), EVENT_TYPES, "unclear_visual_evidence")
    raw["image_quality"] = _upper_allowed(raw.get("image_quality"), IMAGE_QUALITIES, "FAIR")
    raw["evidence_sufficiency"] = _upper_allowed(raw.get("evidence_sufficiency"), EVIDENCE_SUFFICIENCIES, "PARTIAL")
    raw["visual_confidence"] = _confidence(raw.get("visual_confidence"), 0.3)

    # Force shallow old output to become an explicit fallback rather than a fake success.
    required_text = ["visible_scene", "person_observation", "motion_observation", "visual_decision_reason"]
    missing = [k for k in required_text if not str(raw.get(k, "")).strip()]
    if missing:
        return fallback_vlm_uncertain(f"VLM JSON was incomplete; missing fields: {', '.join(missing)}."), {
            "parse_error": "missing_required_vlm_fields",
            "missing_fields": missing,
            "raw_json": raw,
        }

    try:
        return VlmVisualReview.model_validate(raw), {"parse_error": None}
    except ValidationError as e:
        return fallback_vlm_uncertain(f"VLM JSON failed schema validation: {e.errors()[:3]}"), {
            "parse_error": "vlm_schema_validation_failed",
            "errors": e.errors(),
            "raw_json": raw,
        }


def parse_llm_policy_review(raw_text: str, *, ctx: DeepReasoningContext | PoseReasoningContext, vlm: VlmVisualReview) -> tuple[LlmPolicyReview, dict[str, Any]]:
    raw = extract_json_object(raw_text)
    if not raw:
        return fallback_llm_uncertain("LLM did not return parseable JSON.", ctx=ctx, vlm=vlm), {"parse_error": "empty_or_invalid_json"}

    raw["review_type"] = "llm_policy_review"
    raw["schema_version"] = str(raw.get("schema_version") or "1.0")
    raw["policy_alert_decision"] = _upper_allowed(raw.get("policy_alert_decision", raw.get("alert_decision")), ALERT_DECISIONS, "UNCERTAIN")
    raw["policy_severity"] = _upper_allowed(raw.get("policy_severity", raw.get("severity")), SEVERITIES, "LOW")
    raw["policy_confidence"] = _confidence(raw.get("policy_confidence", raw.get("confidence")), 0.3)
    raw["recommended_action"] = _lower_allowed(raw.get("recommended_action"), ACTIONS, "review_only")
    raw.setdefault("score_assessment", {})
    if not isinstance(raw["score_assessment"], dict):
        raw["score_assessment"] = {}
    raw["score_assessment"]["score_ratio"] = ctx.score_ratio
    raw["score_assessment"]["ratio_band"] = _lower_allowed(raw["score_assessment"].get("ratio_band"), RATIO_BANDS, ctx.ratio_band())
    raw["score_assessment"].setdefault("score_reasoning", "Score context was considered conservatively.")
    raw.setdefault("evidence_assessment", {})
    if not isinstance(raw["evidence_assessment"], dict):
        raw["evidence_assessment"] = {}
    raw["evidence_assessment"].setdefault("uses_only_vlm_evidence", True)
    raw["evidence_assessment"].setdefault("has_strong_visual_anomaly_evidence", bool(vlm.anomaly_evidence and vlm.event_type in STRONG_VISUAL_EVENT_TYPES))
    raw["evidence_assessment"].setdefault("has_normality_evidence", bool(vlm.normality_evidence))
    raw["evidence_assessment"].setdefault("has_false_positive_risk", bool(vlm.false_positive_risks))

    if not str(raw.get("decision_reason", "")).strip():
        return fallback_llm_uncertain("LLM JSON was incomplete; missing decision_reason.", ctx=ctx, vlm=vlm), {
            "parse_error": "missing_required_llm_fields",
            "missing_fields": ["decision_reason"],
            "raw_json": raw,
        }

    try:
        return LlmPolicyReview.model_validate(raw), {"parse_error": None}
    except ValidationError as e:
        return fallback_llm_uncertain(f"LLM JSON failed schema validation: {e.errors()[:3]}", ctx=ctx, vlm=vlm), {
            "parse_error": "llm_schema_validation_failed",
            "errors": e.errors(),
            "raw_json": raw,
        }


STRONG_VISUAL_EVENT_TYPES = {
    "fall_or_collapse",
    "person_on_floor",
    "unsafe_equipment_interaction",
    "rapid_unusual_movement",
    "possible_intrusion_or_security_event",
    "suspicious_motion",
}
