"""Tuning history manager.

Records every PID adjustment with context (reason, before/after params,
performance metrics). Generates compressed summaries for LLM prompts
to prevent oscillation and maintain tuning direction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_DIR = Path(__file__).parent.parent / "data" / "logs"


@dataclass(frozen=True)
class TuningRecord:
    """A single tuning adjustment record."""

    timestamp: str
    loop_name: str
    iteration: int
    pid_before: dict[str, float]       # {"kp": ..., "ki": ..., "kd": ...}
    pid_after: dict[str, float]
    metrics_before: dict[str, float]   # Key metrics snapshot
    reason: str                        # LLM's analysis/reason
    confidence: float                  # LLM's confidence (0-1)
    expected_improvement: str          # What LLM expects to improve
    model_used: str                    # Which model was used


@dataclass
class TuningHistory:
    """Manages the full tuning history for a control loop."""

    loop_name: str
    records: list[TuningRecord]

    def add_record(self, record: TuningRecord) -> None:
        """Append a new tuning record."""
        self.records.append(record)
        logger.info(
            "Recorded tuning #%d for %s: Kp %.4f->%.4f, Ki %.4f->%.4f, Kd %.4f->%.4f",
            record.iteration,
            record.loop_name,
            record.pid_before["kp"], record.pid_after["kp"],
            record.pid_before["ki"], record.pid_after["ki"],
            record.pid_before["kd"], record.pid_after["kd"],
        )

    @property
    def iteration_count(self) -> int:
        """Number of tuning iterations so far."""
        return len(self.records)

    def get_recent(self, n: int = 5) -> list[TuningRecord]:
        """Get the most recent N records."""
        return self.records[-n:] if self.records else []

    def detect_oscillation(self, param: str = "kp", window: int = 4) -> bool:
        """Detect if a parameter is oscillating (alternating up/down).

        Returns True if the parameter direction changed in every step
        within the window (e.g., up-down-up-down).
        """
        recent = self.get_recent(window)
        if len(recent) < 3:
            return False

        directions: list[int] = []
        for rec in recent:
            before_val = rec.pid_before.get(param, 0.0)
            after_val = rec.pid_after.get(param, 0.0)
            diff = after_val - before_val
            if abs(diff) < 1e-10:
                directions.append(0)
            else:
                directions.append(1 if diff > 0 else -1)

        # Check for alternating pattern (up-down or down-up every step)
        alternating_count = 0
        for i in range(1, len(directions)):
            if directions[i] != 0 and directions[i - 1] != 0:
                if directions[i] != directions[i - 1]:
                    alternating_count += 1

        # If more than half are alternating, likely oscillating
        return alternating_count >= (len(directions) - 1) * 0.6

    def generate_summary(self, max_records: int = 5) -> str:
        """Generate a compact summary for LLM prompt.

        This is the key anti-oscillation mechanism: by showing the AI
        its own previous adjustments, it can maintain consistent direction.
        """
        recent = self.get_recent(max_records)
        if not recent:
            return "No previous tuning history."

        lines: list[str] = [
            f"## Tuning History (last {len(recent)} of {self.iteration_count} iterations)"
        ]

        for rec in recent:
            kp_b, kp_a = rec.pid_before["kp"], rec.pid_after["kp"]
            ki_b, ki_a = rec.pid_before["ki"], rec.pid_after["ki"]
            kd_b, kd_a = rec.pid_before["kd"], rec.pid_after["kd"]

            kp_dir = _direction_symbol(kp_b, kp_a)
            ki_dir = _direction_symbol(ki_b, ki_a)
            kd_dir = _direction_symbol(kd_b, kd_a)

            lines.append(
                f"  #{rec.iteration}: "
                f"Kp {kp_b:.4f}{kp_dir}{kp_a:.4f}, "
                f"Ki {ki_b:.4f}{ki_dir}{ki_a:.4f}, "
                f"Kd {kd_b:.4f}{kd_dir}{kd_a:.4f} "
                f"| Reason: {rec.reason[:80]}"
            )

        # Trend analysis
        trend_lines = self._analyze_trends()
        if trend_lines:
            lines.append("")
            lines.append("## Trend Analysis")
            lines.extend(trend_lines)

        # Oscillation warnings
        for param in ("kp", "ki", "kd"):
            if self.detect_oscillation(param):
                lines.append(
                    f"  WARNING: {param.upper()} appears to be oscillating! "
                    "Consider smaller adjustments or maintaining current value."
                )

        return "\n".join(lines)

    def _analyze_trends(self) -> list[str]:
        """Analyze parameter adjustment trends over history."""
        if len(self.records) < 2:
            return []

        trends: list[str] = []
        for param in ("kp", "ki", "kd"):
            consecutive_up = 0
            consecutive_down = 0
            for rec in self.records[-5:]:
                diff = rec.pid_after[param] - rec.pid_before[param]
                if diff > 1e-10:
                    consecutive_up += 1
                    consecutive_down = 0
                elif diff < -1e-10:
                    consecutive_down += 1
                    consecutive_up = 0
                # No-change steps: keep current streak (don't reset)

            if consecutive_up >= 3:
                trends.append(
                    f"  {param.upper()} has been increasing for "
                    f"{consecutive_up} consecutive iterations"
                )
            elif consecutive_down >= 3:
                trends.append(
                    f"  {param.upper()} has been decreasing for "
                    f"{consecutive_down} consecutive iterations"
                )

        return trends


def _direction_symbol(before: float, after: float) -> str:
    """Return arrow symbol indicating direction of change."""
    diff = after - before
    if abs(diff) < 1e-10:
        return "="
    return ">" if diff > 0 else "<"  # Using < for decrease to keep compact


def save_history(history: TuningHistory, filepath: Path | str | None = None) -> Path:
    """Save tuning history to a JSON file.

    Args:
        history: The history to save.
        filepath: Target path. Auto-generated if None.

    Returns:
        Path where the file was saved.
    """
    if filepath is None:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = HISTORY_DIR / f"history_{history.loop_name}_{timestamp}.json"
    else:
        filepath = Path(filepath)

    data = {
        "loop_name": history.loop_name,
        "record_count": len(history.records),
        "records": [asdict(r) for r in history.records],
    }

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("History saved to %s (%d records)", filepath, len(history.records))
    return filepath


def load_history(filepath: Path | str) -> TuningHistory:
    """Load tuning history from a JSON file."""
    filepath = Path(filepath)

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = [
        TuningRecord(**rec_data) for rec_data in data.get("records", [])
    ]

    history = TuningHistory(
        loop_name=data.get("loop_name", "unknown"),
        records=records,
    )

    logger.info("Loaded %d records from %s", len(records), filepath)
    return history


def find_latest_history(loop_name: str) -> Path | None:
    """Find the most recent history file for a given loop."""
    if not HISTORY_DIR.exists():
        return None

    pattern = f"history_{loop_name}_*.json"
    files = sorted(HISTORY_DIR.glob(pattern))

    return files[-1] if files else None


def create_record(
    loop_name: str,
    iteration: int,
    pid_before: dict[str, float],
    pid_after: dict[str, float],
    metrics: dict[str, Any],
    reason: str,
    confidence: float,
    expected_improvement: str,
    model_used: str,
) -> TuningRecord:
    """Factory function to create a TuningRecord with current timestamp."""
    return TuningRecord(
        timestamp=datetime.now().isoformat(),
        loop_name=loop_name,
        iteration=iteration,
        pid_before=pid_before,
        pid_after=pid_after,
        metrics_before={
            k: v for k, v in metrics.items()
            if isinstance(v, (int, float))
        },
        reason=reason,
        confidence=confidence,
        expected_improvement=expected_improvement,
        model_used=model_used,
    )
