"""Strategy backends for the experimental lab."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from core.config import AppConfig, PIDParams
from core.history_manager import TuningHistory, TuningRecord
from core.tuner import tune, validate_change
from experimental_lab.models import SessionRecord, StrategyContext, StrategySuggestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyBundle:
    """Container holding the three supported strategies."""

    llm: "LLMStrategy"
    bo: "BayesianStrategy"
    hybrid: "HybridStrategy"


class BaseStrategy:
    """Strategy contract."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def suggest(self, context: StrategyContext) -> StrategySuggestion:
        raise NotImplementedError


class HeuristicStrategy(BaseStrategy):
    """Fallback strategy that nudges PID based on control heuristics."""

    def suggest(self, context: StrategyContext) -> StrategySuggestion:
        loop_config = self._config.get_loop(context.loop_name)
        current = context.current_pid
        metrics = context.metrics
        kp = current.kp
        ki = current.ki
        kd = current.kd
        actions: list[str] = []

        if metrics.is_diverging:
            kp *= 0.82
            kd *= 1.10
            actions.append("reduced Kp for divergence")
        if metrics.overshoot_pct > loop_config.target_metrics.max_overshoot_pct:
            kp *= 0.95
            kd *= 1.08
            actions.append("trimmed overshoot")
        if metrics.settling_time_s > loop_config.target_metrics.max_settling_time_s:
            kp *= 1.08
            actions.append("boosted response speed")
        if metrics.steady_state_error_pct > loop_config.target_metrics.max_sse_pct:
            ki *= 1.10
            actions.append("tightened steady-state error")
        if metrics.oscillation_count > 3:
            kp *= 0.96
            ki *= 0.94
            kd *= 1.08
            actions.append("damped oscillation")
        if metrics.is_saturated:
            kp *= 0.93
            ki *= 0.92
            kd *= 0.97
            actions.append("relieved saturation")

        proposed = PIDParams(kp=kp, ki=ki, kd=kd)
        candidate = validate_change(
            current=current,
            proposed=proposed,
            tuning_config=self._config.tuning,
            loop_config=loop_config,
        )
        return StrategySuggestion(
            pid=candidate,
            reason="Fallback heuristic: " + ", ".join(actions or ["hold parameters"]),
            confidence=0.38,
            expected_improvement="Provide a safe next experiment when LLM is unavailable.",
            converged=False,
            model_used="heuristic-fallback",
            metadata={"source": "heuristic"},
        )


class LLMStrategy(BaseStrategy):
    """Thin wrapper over the existing LLM-based tuner."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._fallback = HeuristicStrategy(config)

    def suggest(self, context: StrategyContext) -> StrategySuggestion:
        history = _records_to_history(context.loop_name, context.records)
        try:
            result = tune(
                config=self._config,
                loop_name=context.loop_name,
                current_pid=context.current_pid,
                metrics=_snapshot_to_metrics(context.metrics),
                data_text=context.data_text,
                history=history,
            )
            return StrategySuggestion(
                pid=result.new_params,
                reason=result.reason,
                confidence=result.confidence,
                expected_improvement=result.expected_improvement,
                converged=result.converged,
                model_used=result.model_used,
                metadata={"source": "llm"},
            )
        except Exception as exc:
            logger.warning("LLM strategy failed: %s", exc)
            fallback = self._fallback.suggest(context)
            return StrategySuggestion(
                pid=fallback.pid,
                reason=f"{fallback.reason}. LLM error: {exc}",
                confidence=fallback.confidence,
                expected_improvement=fallback.expected_improvement,
                converged=False,
                model_used=fallback.model_used,
                metadata={"source": "llm-fallback", "error": str(exc)},
            )


class BayesianStrategy(BaseStrategy):
    """Lightweight Gaussian-process search over the PID space."""

    def suggest(self, context: StrategyContext) -> StrategySuggestion:
        loop_config = self._config.get_loop(context.loop_name)
        observed = [record for record in context.records if record.score is not None]
        candidate_points = _sample_candidates(
            current=context.current_pid,
            records=observed,
            loop_config=loop_config,
            count=180,
        )

        if len(observed) < 3:
            proposed = candidate_points[0]
            candidate = validate_change(
                current=context.current_pid,
                proposed=proposed,
                tuning_config=self._config.tuning,
                loop_config=loop_config,
            )
            return StrategySuggestion(
                pid=candidate,
                reason="BO warm-up: insufficient scored samples, probing a nearby point.",
                confidence=0.41,
                expected_improvement="Collect enough evidence for the surrogate model.",
                converged=False,
                model_used="bo-warmup",
                metadata={"source": "bo", "sample_count": len(observed)},
            )

        x_train = np.array([_normalize_pid(record.pid, loop_config) for record in observed])
        y_train = np.array([float(record.score) for record in observed], dtype=float)
        x_candidates = np.array([_normalize_pid(pid, loop_config) for pid in candidate_points])

        mean, sigma = _predict_gp(x_train, y_train, x_candidates)
        acquisition = _expected_improvement(y_train, mean, sigma)
        best_index = int(np.argmax(acquisition))
        proposed = candidate_points[best_index]

        candidate = validate_change(
            current=context.current_pid,
            proposed=proposed,
            tuning_config=self._config.tuning,
            loop_config=loop_config,
        )
        best_score = float(np.min(y_train))
        return StrategySuggestion(
            pid=candidate,
            reason="BO selected the candidate with the highest expected improvement over observed scores.",
            confidence=0.63,
            expected_improvement=f"Target score below {best_score:.2f} by balancing exploration and exploitation.",
            converged=False,
            model_used="gaussian-process-bo",
            metadata={
                "source": "bo",
                "sample_count": len(observed),
                "best_observed_score": best_score,
                "acquisition": float(acquisition[best_index]),
                "predicted_mean": float(mean[best_index]),
                "predicted_sigma": float(sigma[best_index]),
            },
        )


class HybridStrategy(BaseStrategy):
    """LLM cold start followed by BO once enough scored samples exist."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._llm = LLMStrategy(config)
        self._bo = BayesianStrategy(config)

    def suggest(self, context: StrategyContext) -> StrategySuggestion:
        observed = [record for record in context.records if record.score is not None]
        if len(observed) < 3:
            suggestion = self._llm.suggest(context)
            return StrategySuggestion(
                pid=suggestion.pid,
                reason=suggestion.reason,
                confidence=suggestion.confidence,
                expected_improvement=suggestion.expected_improvement,
                converged=suggestion.converged,
                model_used=suggestion.model_used,
                metadata={**suggestion.metadata, "phase": "cold-start"},
            )
        suggestion = self._bo.suggest(context)
        return StrategySuggestion(
            pid=suggestion.pid,
            reason=suggestion.reason,
            confidence=suggestion.confidence,
            expected_improvement=suggestion.expected_improvement,
            converged=suggestion.converged,
            model_used=suggestion.model_used,
            metadata={**suggestion.metadata, "phase": "bo"},
        )


def build_strategies(config: AppConfig) -> StrategyBundle:
    """Instantiate all strategies once."""
    llm = LLMStrategy(config)
    bo = BayesianStrategy(config)
    hybrid = HybridStrategy(config)
    return StrategyBundle(llm=llm, bo=bo, hybrid=hybrid)


def pick_strategy(bundle: StrategyBundle, name: str) -> BaseStrategy:
    """Lookup helper used by the runner."""
    if name == "llm":
        return bundle.llm
    if name == "bo":
        return bundle.bo
    if name == "hybrid":
        return bundle.hybrid
    raise ValueError(f"Unknown strategy: {name}")


def _records_to_history(loop_name: str, records: list[SessionRecord]) -> TuningHistory:
    history_records: list[TuningRecord] = []
    for record in records:
        history_records.append(
            TuningRecord(
                timestamp=record.created_at,
                loop_name=loop_name,
                iteration=record.iteration_index,
                pid_before=record.prev_pid.to_dict(),
                pid_after=record.pid.to_dict(),
                metrics_before={
                    "overshoot_pct": record.metrics.overshoot_pct,
                    "settling_time_s": record.metrics.settling_time_s,
                    "sse_pct": record.metrics.steady_state_error_pct,
                    "oscillations": record.metrics.oscillation_count,
                },
                reason=record.reason,
                confidence=record.confidence,
                expected_improvement=record.expected_improvement,
                model_used=record.model_used,
            )
        )
    return TuningHistory(loop_name=loop_name, records=history_records)


def _snapshot_to_metrics(snapshot: Any) -> Any:
    class _MetricsProxy:
        overshoot_pct = snapshot.overshoot_pct
        settling_time_s = snapshot.settling_time_s
        steady_state_error_pct = snapshot.steady_state_error_pct
        rise_time_s = snapshot.rise_time_s or 0.0
        oscillation_count = snapshot.oscillation_count
        peak_error = snapshot.peak_error or 0.0
        mean_abs_error = snapshot.mean_abs_error or 0.0
        rms_error = snapshot.rms_error or 0.0
        is_diverging = snapshot.is_diverging
        is_saturated = snapshot.is_saturated
        data_points = snapshot.data_points or 0

        @staticmethod
        def to_prompt_string() -> str:
            lines = [
                f"- Overshoot: {snapshot.overshoot_pct:.1f}%",
                f"- Settling time: {snapshot.settling_time_s:.3f}s",
                f"- Steady-state error: {snapshot.steady_state_error_pct:.2f}%",
                f"- Oscillation count: {snapshot.oscillation_count}",
                f"- Diverging: {'YES' if snapshot.is_diverging else 'No'}",
                f"- Saturated: {'YES' if snapshot.is_saturated else 'No'}",
            ]
            return "\n".join(lines)

        @staticmethod
        def meets_targets(max_overshoot_pct: float, max_settling_time_s: float, max_sse_pct: float) -> bool:
            return (
                snapshot.overshoot_pct <= max_overshoot_pct
                and snapshot.settling_time_s <= max_settling_time_s
                and snapshot.steady_state_error_pct <= max_sse_pct
                and not snapshot.is_diverging
            )

    return _MetricsProxy()


def _sample_candidates(
    *,
    current: PIDParams,
    records: list[SessionRecord],
    loop_config: Any,
    count: int,
) -> list[PIDParams]:
    rng = np.random.default_rng(len(records) * 97 + 11)
    current_norm = np.array(_normalize_pid(current, loop_config))
    best_norm = current_norm
    if records:
        best_record = min(records, key=lambda record: float(record.score or 0.0))
        best_norm = np.array(_normalize_pid(best_record.pid, loop_config))

    candidates: list[PIDParams] = []
    for idx in range(count):
        if idx < count // 3:
            base = current_norm
            spread = 0.08
        elif idx < (count * 2) // 3:
            base = best_norm
            spread = 0.12
        else:
            base = np.array([0.5, 0.5, 0.5])
            spread = 0.35
        point = np.clip(base + rng.normal(0.0, spread, size=3), 0.0, 1.0)
        candidates.append(_denormalize_pid(point, loop_config))
    return candidates


def _normalize_pid(pid: PIDParams, loop_config: Any) -> tuple[float, float, float]:
    limits = loop_config.limits
    return (
        _normalize_value(pid.kp, limits.kp_min, limits.kp_max),
        _normalize_value(pid.ki, limits.ki_min, limits.ki_max),
        _normalize_value(pid.kd, limits.kd_min, limits.kd_max),
    )


def _denormalize_pid(values: np.ndarray, loop_config: Any) -> PIDParams:
    limits = loop_config.limits
    return PIDParams(
        kp=_denormalize_value(values[0], limits.kp_min, limits.kp_max),
        ki=_denormalize_value(values[1], limits.ki_min, limits.ki_max),
        kd=_denormalize_value(values[2], limits.kd_min, limits.kd_max),
    )


def _normalize_value(value: float, lower: float, upper: float) -> float:
    span = max(upper - lower, 1e-9)
    return (value - lower) / span


def _denormalize_value(value: float, lower: float, upper: float) -> float:
    return lower + value * (upper - lower)


def _predict_gp(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_pred: np.ndarray,
    *,
    length_scale: float = 0.28,
    noise: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    y_mean = float(np.mean(y_train))
    centered = y_train - y_mean

    k_train = _rbf_kernel(x_train, x_train, length_scale=length_scale)
    k_train += np.eye(k_train.shape[0]) * noise
    k_cross = _rbf_kernel(x_train, x_pred, length_scale=length_scale)
    k_pred = _rbf_kernel(x_pred, x_pred, length_scale=length_scale)

    chol = np.linalg.cholesky(k_train)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, centered))
    mean = y_mean + k_cross.T @ alpha

    v = np.linalg.solve(chol, k_cross)
    covariance = k_pred - v.T @ v
    sigma = np.sqrt(np.maximum(np.diag(covariance), 1e-9))
    return mean, sigma


def _rbf_kernel(a: np.ndarray, b: np.ndarray, *, length_scale: float) -> np.ndarray:
    a_sq = np.sum(a * a, axis=1).reshape(-1, 1)
    b_sq = np.sum(b * b, axis=1).reshape(1, -1)
    sqdist = np.maximum(a_sq + b_sq - 2.0 * a @ b.T, 0.0)
    return np.exp(-0.5 * sqdist / (length_scale * length_scale))


def _expected_improvement(y_train: np.ndarray, mean: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    best = float(np.min(y_train))
    sigma = np.maximum(sigma, 1e-9)
    improvement = best - mean - 0.05
    z = improvement / sigma
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
    pdf = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return improvement * cdf + sigma * pdf
