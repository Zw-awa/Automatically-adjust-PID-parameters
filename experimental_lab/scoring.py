"""Scoring rules for experimental tuning sessions."""

from __future__ import annotations

from typing import Any

from core.config import TargetMetrics
from experimental_lab.models import MetricSnapshot, ScoreResult

DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "overshoot": 25.0,
    "settling": 25.0,
    "steady_state_error": 20.0,
    "oscillation": 4.0,
    "diverging_penalty": 80.0,
    "saturated_penalty": 24.0,
}


def build_default_score_weights() -> dict[str, float]:
    """Return a copy so sessions can persist a stable snapshot."""
    return dict(DEFAULT_SCORE_WEIGHTS)


def score_metrics(
    metrics: MetricSnapshot,
    targets: TargetMetrics,
    weights: dict[str, float] | None = None,
) -> ScoreResult:
    """Compute a normalized score where lower is better."""
    applied = weights or DEFAULT_SCORE_WEIGHTS

    overshoot_component = _ratio(metrics.overshoot_pct, targets.max_overshoot_pct) * applied[
        "overshoot"
    ]
    settling_component = _ratio(
        metrics.settling_time_s, targets.max_settling_time_s
    ) * applied["settling"]
    sse_component = _ratio(
        metrics.steady_state_error_pct, targets.max_sse_pct
    ) * applied["steady_state_error"]
    oscillation_component = metrics.oscillation_count * applied["oscillation"]
    diverging_component = applied["diverging_penalty"] if metrics.is_diverging else 0.0
    saturated_component = applied["saturated_penalty"] if metrics.is_saturated else 0.0

    score = (
        overshoot_component
        + settling_component
        + sse_component
        + oscillation_component
        + diverging_component
        + saturated_component
    )
    is_good = (
        metrics.overshoot_pct <= targets.max_overshoot_pct
        and metrics.settling_time_s <= targets.max_settling_time_s
        and metrics.steady_state_error_pct <= targets.max_sse_pct
        and not metrics.is_diverging
        and not metrics.is_saturated
    )

    if metrics.is_diverging or score >= 140.0:
        quality_label = "critical"
    elif is_good or score <= 70.0:
        quality_label = "good" if is_good else "watch"
    else:
        quality_label = "watch"

    return ScoreResult(
        score=score,
        is_good=is_good,
        quality_label=quality_label,
        breakdown={
            "overshoot": overshoot_component,
            "settling": settling_component,
            "steady_state_error": sse_component,
            "oscillation": oscillation_component,
            "diverging_penalty": diverging_component,
            "saturated_penalty": saturated_component,
        },
    )


def _ratio(value: float, target: float) -> float:
    baseline = abs(target) if abs(target) > 1e-9 else 1.0
    return value / baseline


def score_from_payload(
    payload: dict[str, Any],
    targets: TargetMetrics,
    weights: dict[str, float] | None = None,
) -> ScoreResult:
    """Build a snapshot from API payload and score it."""
    snapshot = MetricSnapshot(
        overshoot_pct=float(payload.get("overshoot_pct", 0.0)),
        settling_time_s=float(payload.get("settling_time_s", 0.0)),
        steady_state_error_pct=float(payload.get("steady_state_error_pct", 0.0)),
        oscillation_count=int(payload.get("oscillation_count", 0)),
        is_diverging=bool(payload.get("is_diverging", False)),
        is_saturated=bool(payload.get("is_saturated", False)),
    )
    return score_metrics(snapshot, targets, weights=weights)
