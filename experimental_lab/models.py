"""Shared models for the experimental lab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.analyzer import PerformanceMetrics
from core.config import PIDParams

SessionMode = Literal["offline", "simulate"]
StrategyName = Literal["llm", "bo", "hybrid"]
SessionStatus = Literal["idle", "running", "paused", "completed", "failed"]
RecordSource = Literal["auto", "manual"]
QualityLabel = Literal["good", "watch", "critical"]


@dataclass(frozen=True)
class MetricSnapshot:
    """Compact metrics persisted with each experiment record."""

    overshoot_pct: float
    settling_time_s: float
    steady_state_error_pct: float
    oscillation_count: int
    is_diverging: bool = False
    is_saturated: bool = False
    rise_time_s: float | None = None
    peak_error: float | None = None
    mean_abs_error: float | None = None
    rms_error: float | None = None
    data_points: int | None = None

    @classmethod
    def from_performance_metrics(cls, metrics: PerformanceMetrics) -> "MetricSnapshot":
        """Convert analyzer output into a storable snapshot."""
        return cls(
            overshoot_pct=metrics.overshoot_pct,
            settling_time_s=metrics.settling_time_s,
            steady_state_error_pct=metrics.steady_state_error_pct,
            oscillation_count=metrics.oscillation_count,
            is_diverging=metrics.is_diverging,
            is_saturated=metrics.is_saturated,
            rise_time_s=metrics.rise_time_s,
            peak_error=metrics.peak_error,
            mean_abs_error=metrics.mean_abs_error,
            rms_error=metrics.rms_error,
            data_points=metrics.data_points,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON and SQLite payloads."""
        return {
            "overshoot_pct": self.overshoot_pct,
            "settling_time_s": self.settling_time_s,
            "steady_state_error_pct": self.steady_state_error_pct,
            "oscillation_count": self.oscillation_count,
            "is_diverging": self.is_diverging,
            "is_saturated": self.is_saturated,
            "rise_time_s": self.rise_time_s,
            "peak_error": self.peak_error,
            "mean_abs_error": self.mean_abs_error,
            "rms_error": self.rms_error,
            "data_points": self.data_points,
        }


@dataclass(frozen=True)
class ScoreResult:
    """Scoring result used by BO and UI feedback."""

    score: float
    is_good: bool
    quality_label: QualityLabel
    breakdown: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "score": self.score,
            "is_good": self.is_good,
            "quality_label": self.quality_label,
            "breakdown": self.breakdown,
        }


@dataclass(frozen=True)
class SessionRecord:
    """A single observed tuning result."""

    id: int
    session_id: int
    iteration_index: int
    source: RecordSource
    applied: bool
    strategy_name: StrategyName
    model_used: str
    prev_pid: PIDParams
    pid: PIDParams
    metrics: MetricSnapshot
    score: float | None
    is_good: bool | None
    quality_label: QualityLabel | None
    reason: str
    confidence: float
    expected_improvement: str
    raw_data_path: str | None
    note: str
    strategy_metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize record for the API and UI."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "iteration_index": self.iteration_index,
            "source": self.source,
            "applied": self.applied,
            "strategy_name": self.strategy_name,
            "model_used": self.model_used,
            "prev_pid": self.prev_pid.to_dict(),
            "pid": self.pid.to_dict(),
            "metrics": self.metrics.to_dict(),
            "score": self.score,
            "is_good": self.is_good,
            "quality_label": self.quality_label,
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_improvement": self.expected_improvement,
            "raw_data_path": self.raw_data_path,
            "note": self.note,
            "strategy_metadata": self.strategy_metadata,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SessionSummary:
    """Metadata shown in the session list and run header."""

    id: int
    name: str
    loop_name: str
    mode: SessionMode
    strategy: StrategyName
    status: SessionStatus
    notes: str
    created_at: str
    updated_at: str
    record_count: int
    good_count: int
    best_score: float | None
    current_pid: PIDParams
    settings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "id": self.id,
            "name": self.name,
            "loop_name": self.loop_name,
            "mode": self.mode,
            "strategy": self.strategy,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "record_count": self.record_count,
            "good_count": self.good_count,
            "best_score": self.best_score,
            "current_pid": self.current_pid.to_dict(),
            "settings": self.settings,
        }


@dataclass(frozen=True)
class StrategySuggestion:
    """Suggested next parameters from a strategy backend."""

    pid: PIDParams
    reason: str
    confidence: float
    expected_improvement: str
    converged: bool
    model_used: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "pid": self.pid.to_dict(),
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_improvement": self.expected_improvement,
            "converged": self.converged,
            "model_used": self.model_used,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class StrategyContext:
    """Context passed to strategy backends."""

    session_id: int
    loop_name: str
    mode: SessionMode
    strategy_name: StrategyName
    current_pid: PIDParams
    previous_pid: PIDParams
    metrics: MetricSnapshot
    data_text: str
    settings: dict[str, Any]
    records: list[SessionRecord]

