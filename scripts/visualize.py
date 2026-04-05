"""Visualize PID response and tuning history.

Usage:
  python scripts/visualize.py --file data/raw/speed_data.csv
  python scripts/visualize.py --history data/logs/history_speed_*.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib.pyplot as plt
import numpy as np

from core.analyzer import parse_csv_data
from core.history_manager import load_history


def plot_response(filepath: str) -> None:
    """Plot PID step response from CSV data."""
    samples = parse_csv_data(filepath)
    if not samples:
        print("No data to plot")
        return

    t = [s.timestamp for s in samples]
    target = [s.target for s in samples]
    actual = [s.actual for s in samples]
    error = [s.error for s in samples]
    output = [s.output for s in samples]

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    # Response
    axes[0].plot(t, target, "r--", label="Target", linewidth=1.5)
    axes[0].plot(t, actual, "b-", label="Actual", linewidth=1.0)
    axes[0].set_ylabel("Value")
    axes[0].set_title(f"PID Response - {Path(filepath).stem}")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Error
    axes[1].plot(t, error, "g-", linewidth=1.0)
    axes[1].axhline(y=0, color="k", linestyle="-", linewidth=0.5)
    axes[1].set_ylabel("Error")
    axes[1].grid(True, alpha=0.3)

    # Output
    axes[2].plot(t, output, "m-", linewidth=1.0)
    axes[2].set_ylabel("Output")
    axes[2].set_xlabel("Time (s)")
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def plot_tuning_history(filepath: str) -> None:
    """Plot PID parameter changes over tuning iterations."""
    history = load_history(filepath)
    if not history.records:
        print("No records to plot")
        return

    iterations = [r.iteration for r in history.records]
    kp_vals = [r.pid_after["kp"] for r in history.records]
    ki_vals = [r.pid_after["ki"] for r in history.records]
    kd_vals = [r.pid_after["kd"] for r in history.records]

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    axes[0].plot(iterations, kp_vals, "ro-", label="Kp")
    axes[0].set_ylabel("Kp")
    axes[0].set_title(f"Tuning History - {history.loop_name}")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(iterations, ki_vals, "gs-", label="Ki")
    axes[1].set_ylabel("Ki")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(iterations, kd_vals, "b^-", label="Kd")
    axes[2].set_ylabel("Kd")
    axes[2].set_xlabel("Iteration")
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize PID data")
    parser.add_argument("--file", "-f", help="CSV data file to plot")
    parser.add_argument("--history", help="History JSON file to plot")
    args = parser.parse_args()

    if args.file:
        plot_response(args.file)
    elif args.history:
        plot_tuning_history(args.history)
    else:
        print("Specify --file or --history")


if __name__ == "__main__":
    main()
