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
    "physical_altercation",
    "fighting",
    "pushing_or_shoving",
    "grappling_or_wrestling",
    "aggressive_contact",
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
        "physical_altercation",
        "fighting",
        "pushing_or_shoving",
        "grappling_or_wrestling",
        "aggressive_contact",
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



def _first_non_empty(*values: Any) -> str:
    """Return the first non-empty scalar/list/dict-ish value as text."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            items = [str(x).strip() for x in value if str(x).strip()]
            if items:
                return "; ".join(items)
            continue
        if isinstance(value, dict):
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        text = text.strip()
        if text:
            return text
    return ""



_SCORE_ONLY_TERMS = {
    "score", "threshold", "ratio", "percentile", "embedding", "distance",
    "gmm", "knn", "statistical", "statistically", "deviation",
}
_VISUAL_GROUNDING_TERMS = {
    "person", "people", "subject", "body", "arm", "hand", "leg", "head",
    "torso", "limb", "floor", "fall", "collapse", "stumble", "kneel",
    "lean", "push", "shove", "grapple", "fight", "contact", "hold",
    "pull", "hit", "run", "walk", "chair", "object", "equipment",
    "door", "table", "movement", "posture", "visible", "frame",
}


def _looks_score_only_evidence(text: Any) -> bool:
    """True when an alleged VLM evidence item is metric-based, not visual.

    The VLM perception layer must not use gate scores, thresholds, ratios, or model
    internals as visual evidence.  Such metadata belongs to the LLM cognition layer.
    A sentence such as "pose score exceeds the threshold" is not visual evidence even
    if it also contains generic words like "motion" or "posture".
    """
    s = str(text or "").strip().lower()
    if not s:
        return False
    has_score = any(re.search(r"\b" + re.escape(term) + r"\b", s) for term in _SCORE_ONLY_TERMS)
    if not has_score:
        return False
    concrete_visual_terms = {
        "hand", "hands", "arm", "arms", "leg", "legs", "head", "torso",
        "floor", "knees", "body", "contact", "push", "shove", "grapple",
        "fight", "hit", "pull", "hold", "restrain", "collapse", "fall",
        "stumble", "lean", "chair", "table", "equipment", "door", "object",
    }
    has_concrete_visual_detail = any(
        re.search(r"\b" + re.escape(term) + r"\b", s) for term in concrete_visual_terms
    )
    return not has_concrete_visual_detail


def _listify_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    return [text] if text else []


def _filter_vlm_score_only_evidence(raw: dict[str, Any]) -> None:
    """Remove score-only statements from VLM anomaly_evidence.

    This protects the P2C boundary.  The VLM may describe visible posture/motion/contact,
    but it must not treat "score above threshold" as visual evidence.  Score context is
    still preserved for the LLM through gate metadata.
    """
    evidence = _listify_text(raw.get("anomaly_evidence"))
    kept: list[str] = []
    removed: list[str] = []
    for item in evidence:
        if _looks_score_only_evidence(item):
            removed.append(item)
        else:
            kept.append(item)
    raw["anomaly_evidence"] = kept

    if removed:
        risks = _listify_text(raw.get("false_positive_risks"))
        risks.append(
            "Parser removed score/threshold-only text from VLM anomaly_evidence because VLM evidence must be visual only."
        )
        raw["false_positive_risks"] = risks
        raw.setdefault("_normalization_warnings", [])
        raw["_normalization_warnings"].append({
            "type": "score_only_vlm_evidence_removed",
            "removed_items": removed,
        })


def _normalize_vlm_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Make local VLM outputs robust without changing the P2C contract.

    Local multimodal models often return semantically correct JSON with slightly different
    key names, or omit the explanatory `visual_decision_reason` while still providing scene,
    person, and motion fields.  The previous parser threw away the whole perception payload
    in those cases, causing the dashboard to show the generic UNCERTAIN fallback for many
    events.  This normalizer preserves usable perception text and synthesizes only the missing
    explanation field when needed.
    """
    if not isinstance(raw, dict):
        return {}

    # Common naming variants produced by MiniCPM/LLaVA/Qwen-VL-like local models.
    raw.setdefault("visible_scene", _first_non_empty(
        raw.get("visible_scene"), raw.get("scene"), raw.get("scene_description"),
        raw.get("global_perception"), raw.get("environment"), raw.get("visible_environment"),
    ))
    raw.setdefault("person_observation", _first_non_empty(
        raw.get("person_observation"), raw.get("people_observation"), raw.get("subject_observation"),
        raw.get("local_perception"), raw.get("person_description"), raw.get("people"),
        raw.get("subjects"), raw.get("human_observation"),
    ))
    raw.setdefault("motion_observation", _first_non_empty(
        raw.get("motion_observation"), raw.get("motion_description"), raw.get("action_observation"),
        raw.get("kinetic_description"), raw.get("temporal_description"), raw.get("movement"),
        raw.get("actions"), raw.get("activity"),
    ))
    raw.setdefault("visual_decision_reason", _first_non_empty(
        raw.get("visual_decision_reason"), raw.get("decision_reason"), raw.get("reason"),
        raw.get("rationale"), raw.get("explanation"), raw.get("visual_reason"),
        raw.get("why"), raw.get("assessment"),
    ))

    # Enforce the P2C boundary before validation: VLM evidence must be visual,
    # not based on gate scores/thresholds/ratios.
    _filter_vlm_score_only_evidence(raw)
    if _upper_allowed(raw.get("visual_alert_decision", raw.get("alert_decision")), ALERT_DECISIONS, "UNCERTAIN") == "YES" and not _listify_text(raw.get("anomaly_evidence")):
        raw["visual_alert_decision"] = "UNCERTAIN"
        raw.setdefault("_normalization_warnings", [])
        raw["_normalization_warnings"].append({
            "type": "downgraded_yes_without_visual_anomaly_evidence",
            "reason": "The VLM perception flag was YES, but no concrete visual anomaly_evidence remained after score-only evidence filtering.",
        })

    # If the VLM gave the three perception fields but forgot the reason, keep the useful
    # perception and synthesize a neutral reason instead of discarding everything.
    if not str(raw.get("visual_decision_reason", "")).strip():
        decision = _upper_allowed(raw.get("visual_alert_decision", raw.get("alert_decision")), ALERT_DECISIONS, "UNCERTAIN")
        if decision == "YES" and raw.get("anomaly_evidence"):
            raw["visual_decision_reason"] = "Perception flag set to YES because concrete concerning visual cues were described in anomaly_evidence; final rule cognition remains with the LLM."
        elif decision == "NO" and raw.get("normality_evidence"):
            raw["visual_decision_reason"] = "Perception flag set to NO because the described visible activity appears ordinary or benign; final rule cognition remains with the LLM."
        elif str(raw.get("motion_observation", "")).strip() or str(raw.get("person_observation", "")).strip():
            raw["visual_decision_reason"] = "The VLM provided perception details but omitted a separate visual_decision_reason; the parser preserved the perception text and marked the reason as synthesized."

    return raw

def parse_vlm_visual_review(raw_text: str) -> tuple[VlmVisualReview, dict[str, Any]]:
    raw = extract_json_object(raw_text)
    if not raw:
        return fallback_vlm_uncertain("VLM did not return parseable JSON."), {"parse_error": "empty_or_invalid_json"}

    raw = _normalize_vlm_json(raw)

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

    # Preserve partially useful VLM perception when possible.  Only fall back to the generic
    # UNCERTAIN object when core perception fields are absent; a missing reason is synthesized
    # above and reported as a warning, not treated as total failure.
    core_required_text = ["visible_scene", "person_observation", "motion_observation"]
    missing_core = [k for k in core_required_text if not str(raw.get(k, "")).strip()]
    if missing_core:
        return fallback_vlm_uncertain(f"VLM JSON was incomplete; missing core perception fields: {', '.join(missing_core)}."), {
            "parse_error": "missing_required_vlm_fields",
            "missing_fields": missing_core,
            "raw_json": raw,
        }
    if not str(raw.get("visual_decision_reason", "")).strip():
        raw["visual_decision_reason"] = "The VLM omitted visual_decision_reason; perception text was preserved and final cognition is deferred to the LLM."

    try:
        parse_info: dict[str, Any] = {"parse_error": None, "raw_json": raw}
        if raw.get("_normalization_warnings"):
            parse_info["normalization_warnings"] = raw.get("_normalization_warnings")
        if "visual_decision_reason" not in extract_json_object(raw_text):
            parse_info["normalization_warnings"] = parse_info.get("normalization_warnings", []) + [{
                "type": "synthesized_visual_decision_reason",
                "reason": raw.get("visual_decision_reason"),
            }]
        return VlmVisualReview.model_validate(raw), parse_info
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
    "physical_altercation",
    "fighting",
    "pushing_or_shoving",
    "grappling_or_wrestling",
    "aggressive_contact",
}
