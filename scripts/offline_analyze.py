"""Offline analysis of CSV data files.

Analyzes data without calling LLM - useful for quick diagnostics.

Usage:
  python scripts/offline_analyze.py --file data/raw/speed_data.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.analyzer import analyze, parse_csv_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze PID data offline")
    parser.add_argument("--file", "-f", required=True, help="CSV data file")
    args = parser.parse_args()

    print(f"\nAnalyzing: {args.file}\n")

    samples = parse_csv_data(args.file)
    if not samples:
        print("ERROR: No data found in file")
        return

    print(f"Data points: {len(samples)}")
    print(f"Time span: {samples[0].timestamp:.3f} - {samples[-1].timestamp:.3f}s")
    print(f"Target: {samples[0].target:.2f}")
    print()

    metrics = analyze(samples)
    print("Performance Metrics:")
    print(metrics.to_prompt_string())

    # Quick diagnosis
    print("\nDiagnosis:")
    if metrics.is_diverging:
        print("  [CRITICAL] System is DIVERGING - reduce Kp immediately!")
    if metrics.is_saturated:
        print("  [WARNING] Output is saturating - reduce overall gains")
    if metrics.overshoot_pct > 20:
        print(f"  [HIGH] Overshoot too large ({metrics.overshoot_pct:.1f}%) - reduce Kp or increase Kd")
    elif metrics.overshoot_pct > 5:
        print(f"  [MEDIUM] Moderate overshoot ({metrics.overshoot_pct:.1f}%)")
    if metrics.oscillation_count > 5:
        print(f"  [HIGH] Excessive oscillation ({metrics.oscillation_count} cycles) - reduce Kp, increase Kd")
    if metrics.steady_state_error_pct > 5:
        print(f"  [HIGH] Large steady-state error ({metrics.steady_state_error_pct:.1f}%) - increase Ki")
    if (
        not metrics.is_diverging
        and metrics.overshoot_pct <= 5
        and metrics.oscillation_count <= 2
        and metrics.steady_state_error_pct <= 1
    ):
        print("  [OK] Performance looks good!")


if __name__ == "__main__":
    main()
