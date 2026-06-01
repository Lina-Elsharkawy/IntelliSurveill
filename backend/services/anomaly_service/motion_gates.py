from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import (
    HIGH_SPEED_THRESHOLD,
    ABRUPT_ANGLE_THRESHOLD,
    MIN_TURN_SPEED,
    MAX_TRACK_GAP,
)


@dataclass(frozen=True)
class GateDecision:
    name: str
    fired: bool
    score_value: float | None
    threshold_value: float | None
    reason: str
    details: dict[str, Any]


def _first_number(stats: dict[str, Any], keys: list[str], default: float | None = None) -> float | None:
    for key in keys:
        value = stats.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _first_int(stats: dict[str, Any], keys: list[str], default: int | None = None) -> int | None:
    value = _first_number(stats, keys, None)
    return int(value) if value is not None else default


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_motion_gates(
    motion_stats: dict[str, Any] | None,
    *,
    high_speed_threshold: float = HIGH_SPEED_THRESHOLD,
    abrupt_angle_threshold: float = ABRUPT_ANGLE_THRESHOLD,
    min_turn_speed: float = MIN_TURN_SPEED,
    max_track_gap: int = MAX_TRACK_GAP,
    edge_high_speed_gate: bool | None = None,
    edge_abrupt_direction_gate: bool | None = None,
    edge_track_instability_gate: bool | None = None,
) -> dict[str, GateDecision]:
    stats = motion_stats or {}

    max_speed_norm = _first_number(stats, ["max_speed_norm", "speed_norm", "max_speed", "speed"])
    max_turn_angle = _first_number(stats, ["max_turn_angle", "turn_angle", "max_angle", "angle"])
    turn_speed = _first_number(stats, ["turn_speed", "max_turn_speed", "speed_at_turn", "turn_speed_norm"], 0.0)
    track_gap_count = _first_int(stats, ["track_gap_count", "gap_count", "max_track_gap", "lost_frames"], 0)
    instability_reason = str(stats.get("track_instability_reason") or stats.get("instability_reason") or "").strip()

    high_speed = bool(max_speed_norm is not None and max_speed_norm > high_speed_threshold)
    abrupt = bool(
        max_turn_angle is not None
        and max_turn_angle >= abrupt_angle_threshold
        and (turn_speed or 0.0) >= min_turn_speed
    )
    unstable = bool((track_gap_count or 0) > max_track_gap or instability_reason)

    if edge_high_speed_gate is not None:
        high_speed = high_speed or bool(edge_high_speed_gate)
    if edge_abrupt_direction_gate is not None:
        abrupt = abrupt or bool(edge_abrupt_direction_gate)
    if edge_track_instability_gate is not None:
        unstable = unstable or bool(edge_track_instability_gate)

    # ------------------------------------------------------------------
    # Person interaction gate
    # ------------------------------------------------------------------
    # The Jetson edge script already sends interaction/nearby-person metadata
    # inside motion_stats. The old backend gate logic ignored these fields,
    # so fight/contact-like two-person events could have all motion gates false.
    #
    # This gate is intentionally separate from high_speed/abrupt/instability:
    # it detects suspicious close-person interaction, not raw movement speed.
    # ------------------------------------------------------------------
    nearby = _as_dict(stats.get("nearby_person"))
    interaction = _as_dict(stats.get("interaction"))

    interaction_event = bool(
        stats.get("interaction_event")
        or interaction.get("interaction_event")
        or nearby.get("interaction_event")
    )

    has_close_person = bool(nearby.get("has_close_person"))

    nearby_person_count = _safe_float(nearby.get("nearby_person_count"), 0.0) or 0.0
    selected_track_count = _safe_float(interaction.get("selected_track_count"), 0.0) or 0.0

    min_other_person_distance = _safe_float(nearby.get("min_other_person_distance"))
    max_other_person_iou = _safe_float(nearby.get("max_other_person_iou"), 0.0) or 0.0

    # Conservative interaction thresholds.
    # These match the kind of event you showed:
    # min distance around 0.08 and IoU around 0.15 should fire.
    close_distance_threshold = 0.12
    interaction_iou_threshold = 0.05

    person_interaction = bool(
        interaction_event
        or has_close_person
        or selected_track_count >= 2
        or (
            min_other_person_distance is not None
            and min_other_person_distance <= close_distance_threshold
        )
        or max_other_person_iou >= interaction_iou_threshold
    )

    if interaction_event:
        person_interaction_reason = "interaction_event=true"
    elif has_close_person:
        person_interaction_reason = "nearby_person.has_close_person=true"
    elif selected_track_count >= 2:
        person_interaction_reason = f"selected_track_count={selected_track_count:.0f}"
    elif min_other_person_distance is not None and min_other_person_distance <= close_distance_threshold:
        person_interaction_reason = (
            f"min_other_person_distance={min_other_person_distance:.4f} "
            f"<= {close_distance_threshold:.4f}"
        )
    elif max_other_person_iou >= interaction_iou_threshold:
        person_interaction_reason = (
            f"max_other_person_iou={max_other_person_iou:.4f} "
            f">= {interaction_iou_threshold:.4f}"
        )
    else:
        person_interaction_reason = "Person-interaction gate did not fire"

    return {
        "high_speed": GateDecision(
            name="high_speed",
            fired=high_speed,
            score_value=max_speed_norm,
            threshold_value=high_speed_threshold,
            reason=(
                f"max_speed_norm={max_speed_norm:.4f} exceeded {high_speed_threshold:.4f}"
                if high_speed and max_speed_norm is not None else "High-speed gate did not fire"
            ),
            details={"max_speed_norm": max_speed_norm},
        ),
        "abrupt_direction_change": GateDecision(
            name="abrupt_direction_change",
            fired=abrupt,
            score_value=max_turn_angle,
            threshold_value=abrupt_angle_threshold,
            reason=(
                f"max_turn_angle={max_turn_angle:.1f} with turn_speed={turn_speed:.4f}"
                if abrupt and max_turn_angle is not None else "Abrupt-direction gate did not fire"
            ),
            details={
                "max_turn_angle": max_turn_angle,
                "turn_speed": turn_speed,
                "min_turn_speed": min_turn_speed,
            },
        ),
        "track_instability": GateDecision(
            name="track_instability",
            fired=unstable,
            score_value=float(track_gap_count or 0),
            threshold_value=float(max_track_gap),
            reason=(
                instability_reason
                or f"track_gap_count={track_gap_count} exceeded {max_track_gap}"
                if unstable else "Track-instability gate did not fire"
            ),
            details={
                "track_gap_count": track_gap_count,
                "track_instability_reason": instability_reason,
            },
        ),
        "person_interaction": GateDecision(
            name="person_interaction",
            fired=person_interaction,
            score_value=min_other_person_distance,
            threshold_value=close_distance_threshold,
            reason=person_interaction_reason,
            details={
                "interaction_event": interaction_event,
                "has_close_person": has_close_person,
                "nearby_person_count": nearby_person_count,
                "selected_track_count": selected_track_count,
                "min_other_person_distance": min_other_person_distance,
                "close_distance_threshold": close_distance_threshold,
                "max_other_person_iou": max_other_person_iou,
                "interaction_iou_threshold": interaction_iou_threshold,
            },
        ),
    }


def build_candidate_reasons(
    *,
    distribution_gate: bool,
    motion_decisions: dict[str, GateDecision],
) -> list[str]:
    reasons: list[str] = []
    if distribution_gate:
        reasons.append("distribution_score")
    for name, decision in motion_decisions.items():
        if decision.fired:
            reasons.append(name)
    return reasons


def assign_priority(
    *,
    final_score: float,
    p97: float | None,
    p99: float | None,
    p99_5: float | None,
    candidate_reasons: list[str],
) -> str:
    if p99_5 is not None and final_score > p99_5:
        return "very_high"
    if p99 is not None and final_score > p99:
        return "high"
    if len(candidate_reasons) >= 2:
        return "high"
    if p97 is not None and final_score > p97:
        return "medium"
    if candidate_reasons == ["high_speed"]:
        return "medium"
    if "person_interaction" in candidate_reasons:
        return "medium"
    if any(r in candidate_reasons for r in ("abrupt_direction_change", "track_instability")):
        return "low"
    return "normal"