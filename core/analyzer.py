"""PID performance analyzer.

Computes control-system metrics from time-series data:
overshoot, settling time, steady-state error, rise time, oscillation count.
All computations are pure math (numpy) - no LLM involved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerformanceMetrics:
    """Computed performance metrics for a PID response."""

    overshoot_pct: float          # Peak overshoot as percentage of target
    settling_time_s: float        # Time to reach and stay within 2% band
    steady_state_error_pct: float # Final error as percentage of target
    rise_time_s: float            # Time from 10% to 90% of target
    oscillation_count: int        # Number of zero-crossings in error signal
    peak_error: float             # Maximum absolute error
    mean_abs_error: float         # Average absolute error
    rms_error: float              # Root-mean-square error
    is_diverging: bool            # True if error is growing over time
    is_saturated: bool            # True if output is hitting limits
    data_points: int              # Number of samples analyzed

    def to_prompt_string(self) -> str:
        """Format metrics as a human-readable string for LLM prompt."""
        lines = [
            f"- Overshoot: {self.overshoot_pct:.1f}%",
            f"- Settling time: {self.settling_time_s:.3f}s",
            f"- Steady-state error: {self.steady_state_error_pct:.2f}%",
            f"- Rise time: {self.rise_time_s:.3f}s",
            f"- Oscillation count: {self.oscillation_count}",
            f"- Peak error: {self.peak_error:.4f}",
            f"- Mean absolute error: {self.mean_abs_error:.4f}",
            f"- RMS error: {self.rms_error:.4f}",
            f"- Diverging: {'YES' if self.is_diverging else 'No'}",
            f"- Saturated: {'YES' if self.is_saturated else 'No'}",
            f"- Data points: {self.data_points}",
        ]
        return "\n".join(lines)

    def meets_targets(
        self,
        max_overshoot_pct: float,
        max_settling_time_s: float,
        max_sse_pct: float,
    ) -> bool:
        """Check if metrics satisfy target requirements."""
        return (
            self.overshoot_pct <= max_overshoot_pct
            and self.settling_time_s <= max_settling_time_s
            and self.steady_state_error_pct <= max_sse_pct
            and not self.is_diverging
        )


@dataclass(frozen=True)
class DataSample:
    """A single data point from the control system."""

    timestamp: float  # seconds (relative or absolute)
    target: float     # setpoint
    actual: float     # measured value
    error: float      # target - actual
    output: float     # controller output (PWM duty, voltage, etc.)


def parse_csv_data(
    filepath: str,
    delimiter: str = ",",
    has_header: bool = True,
) -> list[DataSample]:
    """Parse CSV file into DataSample list.

    Expected columns: timestamp, target, actual, error, output
    If only 3 columns: timestamp, target, actual (error computed automatically)
    """
    samples: list[DataSample] = []

    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if has_header and i == 0:
                continue

            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split(delimiter)
            try:
                if len(parts) >= 5:
                    ts = float(parts[0].strip())
                    target = float(parts[1].strip())
                    actual = float(parts[2].strip())
                    error = float(parts[3].strip())
                    output = float(parts[4].strip())
                elif len(parts) >= 3:
                    ts = float(parts[0].strip())
                    target = float(parts[1].strip())
                    actual = float(parts[2].strip())
                    error = target - actual
                    output = 0.0
                else:
                    logger.warning("Line %d: insufficient columns, skipping", i)
                    continue

                samples.append(DataSample(
                    timestamp=ts,
                    target=target,
                    actual=actual,
                    error=error,
                    output=output,
                ))
            except ValueError as e:
                logger.warning("Line %d: parse error: %s", i, e)
                continue

    logger.info("Parsed %d data samples from %s", len(samples), filepath)
    return samples


def analyze(
    samples: Sequence[DataSample],
    settling_band_pct: float = 2.0,
    output_limits: tuple[float, float] | None = None,
) -> PerformanceMetrics:
    """Analyze PID response data and compute performance metrics.

    Args:
        samples: Time-ordered data points.
        settling_band_pct: Percentage band for settling time (default 2%).
        output_limits: (min, max) tuple for saturation detection. None = skip.

    Returns:
        PerformanceMetrics with computed values.
    """
    if len(samples) < 3:
        logger.warning("Too few samples (%d) for meaningful analysis", len(samples))
        return PerformanceMetrics(
            overshoot_pct=0.0,
            settling_time_s=0.0,
            steady_state_error_pct=0.0,
            rise_time_s=0.0,
            oscillation_count=0,
            peak_error=0.0,
            mean_abs_error=0.0,
            rms_error=0.0,
            is_diverging=False,
            is_saturated=False,
            data_points=len(samples),
        )

    timestamps = np.array([s.timestamp for s in samples])
    targets = np.array([s.target for s in samples])
    actuals = np.array([s.actual for s in samples])
    errors = np.array([s.error for s in samples])
    outputs = np.array([s.output for s in samples])

    # Normalize time to start from 0
    t = timestamps - timestamps[0]

    # Use final target as reference for percentage calculations
    target_ref = float(targets[-1])
    if abs(target_ref) < 1e-10:
        target_ref = float(np.mean(targets)) or 1.0  # Fallback for zero target

    # --- Overshoot ---
    overshoot_pct = _compute_overshoot(actuals, targets, target_ref)

    # --- Settling time ---
    settling_time_s = _compute_settling_time(t, actuals, targets, settling_band_pct)

    # --- Steady-state error ---
    n_tail = max(1, len(samples) // 5)  # Last 20% of data
    tail_errors = errors[-n_tail:]
    sse = float(np.mean(np.abs(tail_errors)))
    sse_pct = (sse / abs(target_ref)) * 100.0

    # --- Rise time (10% to 90%) ---
    rise_time_s = _compute_rise_time(t, actuals, targets)

    # --- Oscillation count ---
    oscillation_count = _count_oscillations(errors)

    # --- Error statistics ---
    abs_errors = np.abs(errors)
    peak_error = float(np.max(abs_errors))
    mean_abs_error = float(np.mean(abs_errors))
    rms_error = float(np.sqrt(np.mean(errors ** 2)))

    # --- Divergence detection ---
    is_diverging = _detect_divergence(abs_errors)

    # --- Saturation detection ---
    is_saturated = False
    if output_limits is not None:
        out_min, out_max = output_limits
        span = abs(out_max - out_min)
        tol = max(1e-3, 0.01 * span)
        saturated_samples = np.sum(
            (outputs <= out_min + tol)
            | (outputs >= out_max - tol)
        )
        is_saturated = saturated_samples > len(outputs) * 0.1

    return PerformanceMetrics(
        overshoot_pct=overshoot_pct,
        settling_time_s=settling_time_s,
        steady_state_error_pct=sse_pct,
        rise_time_s=rise_time_s,
        oscillation_count=oscillation_count,
        peak_error=peak_error,
        mean_abs_error=mean_abs_error,
        rms_error=rms_error,
        is_diverging=is_diverging,
        is_saturated=is_saturated,
        data_points=len(samples),
    )


def _compute_overshoot(
    actuals: NDArray[np.floating],
    targets: NDArray[np.floating],
    target_ref: float,
) -> float:
    """Compute percentage overshoot relative to step size."""
    final_target = targets[-1]
    step_size = abs(float(final_target - targets[0]))
    if step_size < 1e-10:
        step_size = abs(target_ref)  # Fallback for zero step

    # Determine direction of step
    if final_target >= targets[0]:
        # Positive step: overshoot = max value above target
        peak = float(np.max(actuals))
        if peak > final_target:
            return ((peak - final_target) / step_size) * 100.0
    else:
        # Negative step: overshoot = min value below target
        trough = float(np.min(actuals))
        if trough < final_target:
            return ((final_target - trough) / step_size) * 100.0

    return 0.0


def _compute_settling_time(
    t: NDArray[np.floating],
    actuals: NDArray[np.floating],
    targets: NDArray[np.floating],
    band_pct: float,
) -> float:
    """Compute settling time (last time signal exits the settling band)."""
    final_target = targets[-1]
    band = abs(final_target) * band_pct / 100.0
    if band < 1e-10:
        band = 0.01  # Minimum band for zero target

    within_band = np.abs(actuals - final_target) <= band

    # Find last time the signal was outside the band
    outside_indices = np.where(~within_band)[0]
    if len(outside_indices) == 0:
        return 0.0  # Always within band

    last_outside = outside_indices[-1]
    if last_outside >= len(t) - 1:
        return float(t[-1])  # Never settled

    return float(t[last_outside + 1])  # First sample permanently inside band


def _compute_rise_time(
    t: NDArray[np.floating],
    actuals: NDArray[np.floating],
    targets: NDArray[np.floating],
) -> float:
    """Compute rise time from 10% to 90% of target value."""
    initial = actuals[0]
    final_target = targets[-1]
    step_size = final_target - initial

    if abs(step_size) < 1e-10:
        return 0.0

    val_10 = initial + 0.1 * step_size
    val_90 = initial + 0.9 * step_size

    t_10 = None
    t_90 = None

    if step_size > 0:
        idx_10 = np.where(actuals >= val_10)[0]
        idx_90 = np.where(actuals >= val_90)[0]
    else:
        idx_10 = np.where(actuals <= val_10)[0]
        idx_90 = np.where(actuals <= val_90)[0]

    if len(idx_10) > 0:
        t_10 = float(t[idx_10[0]])
    if len(idx_90) > 0:
        t_90 = float(t[idx_90[0]])

    if t_10 is not None and t_90 is not None:
        return t_90 - t_10

    return float(t[-1])  # Fallback: never reached


def _count_oscillations(errors: NDArray[np.floating]) -> int:
    """Count zero-crossings in error signal (proxy for oscillation count)."""
    if len(errors) < 2:
        return 0

    sign_changes = np.diff(np.sign(errors))
    crossings = np.count_nonzero(sign_changes)

    # Each full oscillation is 2 crossings
    return crossings // 2


def _detect_divergence(
    abs_errors: NDArray[np.floating],
    window_fraction: float = 0.3,
) -> bool:
    """Detect if error is growing over time (divergence).

    Compares mean error of last 30% vs first 30% of data.
    """
    n = len(abs_errors)
    if n < 6:
        return False

    window = max(2, int(n * window_fraction))
    early_mean = float(np.mean(abs_errors[:window]))
    late_mean = float(np.mean(abs_errors[-window:]))

    # Diverging if late error is significantly larger than early error
    if early_mean < 1e-10:
        return late_mean > 0.1

    return late_mean > early_mean * 1.5


def format_data_for_prompt(
    samples: Sequence[DataSample],
    max_rows: int = 30,
) -> str:
    """Format data samples as a compact table for LLM prompt.

    Downsamples if more than max_rows to save tokens.
    """
    if len(samples) <= max_rows:
        selected = list(samples)
    else:
        # Uniform downsampling
        indices = np.linspace(0, len(samples) - 1, max_rows, dtype=int)
        selected = [samples[i] for i in indices]

    lines = ["timestamp, target, actual, error"]
    for s in selected:
        lines.append(f"{s.timestamp:.4f}, {s.target:.3f}, {s.actual:.3f}, {s.error:.4f}")

    return "\n".join(lines)
