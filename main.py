"""PID Auto-Tuner - Main Entry Point.

Two operating modes:
  1. Offline: Load CSV data file -> analyze -> LLM suggest -> output params
  2. Online:  Serial read -> periodic analyze -> LLM suggest -> serial send

Usage:
  python main.py offline --file data.csv --loop speed
  python main.py online --port COM3 --loop speed --interval 10
  python main.py simulate --loop speed --iterations 5
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from core.analyzer import (
    DataSample,
    PerformanceMetrics,
    analyze,
    format_data_for_prompt,
    parse_csv_data,
)
from core.config import AppConfig, PIDParams, load_config, save_config
from core.data_collector import DataCollector
from core.history_manager import (
    TuningHistory,
    create_record,
    find_latest_history,
    load_history,
    save_history,
)
from core.serial_manager import SerialManager, ParsedMessage
from core.tuner import TuneResult, tune

logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown requested (signal %d)", signum)


# ──────────────────────────────────────────────
#  Offline Mode
# ──────────────────────────────────────────────

def run_offline(
    config: AppConfig,
    loop_name: str,
    data_file: str,
    history_file: str | None = None,
) -> None:
    """Run offline tuning from a CSV data file.

    Workflow:
      1. Load data from CSV
      2. Compute performance metrics
      3. Load tuning history (if exists)
      4. Call LLM for parameter suggestions
      5. Display results
      6. Save history
    """
    print(f"\n{'='*60}")
    print(f"  PID Auto-Tuner - Offline Mode")
    print(f"  Loop: {loop_name}")
    print(f"  Data: {data_file}")
    print(f"{'='*60}\n")

    loop_config = config.get_loop(loop_name)

    # 1. Load data
    print("[1/5] Loading data...")
    samples = parse_csv_data(data_file)
    if len(samples) < 5:
        print(f"ERROR: Only {len(samples)} samples found. Need at least 5.")
        return

    print(f"  Loaded {len(samples)} data points")

    # 2. Analyze
    print("[2/5] Analyzing performance...")
    metrics = analyze(samples)
    print(metrics.to_prompt_string())

    current_pid = loop_config.pid
    print(f"\n  Current PID: Kp={current_pid.kp}, Ki={current_pid.ki}, Kd={current_pid.kd}")

    # Check if already good
    targets_met = metrics.meets_targets(
        loop_config.target_metrics.max_overshoot_pct,
        loop_config.target_metrics.max_settling_time_s,
        loop_config.target_metrics.max_sse_pct,
    )
    if targets_met:
        print("\n  All targets met! Current parameters look good.")
        print("  Consulting LLM for verification...\n")

    # 3. Load history
    print("[3/5] Loading tuning history...")
    history = _load_or_create_history(loop_name, history_file)
    if history.records:
        print(f"  Found {len(history.records)} previous tuning records")
    else:
        print("  No previous history found (starting fresh)")

    # 4. Call LLM
    print("[4/5] Consulting LLM for parameter suggestions...")
    data_text = format_data_for_prompt(
        samples, max_rows=config.tuning.data_sample_count
    )

    try:
        result = tune(
            config=config,
            loop_name=loop_name,
            current_pid=current_pid,
            metrics=metrics,
            data_text=data_text,
            history=history,
        )
    except Exception as e:
        print(f"\n  ERROR: LLM call failed: {e}")
        print("  Check your API key and network connection.")
        return

    # 5. Display results
    _display_tune_result(current_pid, result, loop_name)

    # Update history
    record = create_record(
        loop_name=loop_name,
        iteration=history.iteration_count + 1,
        pid_before=current_pid.to_dict(),
        pid_after=result.new_params.to_dict(),
        metrics={
            "overshoot_pct": metrics.overshoot_pct,
            "settling_time_s": metrics.settling_time_s,
            "sse_pct": metrics.steady_state_error_pct,
            "oscillations": metrics.oscillation_count,
        },
        reason=result.reason,
        confidence=result.confidence,
        expected_improvement=result.expected_improvement,
        model_used=result.model_used,
    )
    history.add_record(record)
    history_path = save_history(history)
    print(f"\n  History saved to: {history_path}")

    # Update config with new params
    if not result.converged:
        config.update_loop_pid(loop_name, result.new_params)
        save_config(config)
        print("  Config updated with new parameters\n")

    # Output serial command
    cmd = result.new_params.format_command(loop_name)
    print(f"\n  Serial command (copy to send manually):")
    print(f"  >>> {cmd}")
    print()


# ──────────────────────────────────────────────
#  Online Mode
# ──────────────────────────────────────────────

def run_online(
    config: AppConfig,
    loop_name: str,
    port: str | None = None,
    interval: float | None = None,
    max_iterations: int | None = None,
) -> None:
    """Run online tuning with real-time serial communication.

    Workflow (repeating):
      1. Read serial data continuously
      2. Every <interval> seconds, analyze buffered data
      3. Call LLM for suggestions
      4. Optionally send new params via serial
      5. Repeat until converged or max iterations
    """
    signal.signal(signal.SIGINT, _signal_handler)
    global _shutdown_requested
    _shutdown_requested = False

    # Override config if CLI args provided
    serial_config = config.serial
    if port:
        from core.config import SerialConfig
        serial_config = SerialConfig(
            port=port,
            baudrate=serial_config.baudrate,
            timeout=serial_config.timeout,
            encoding=serial_config.encoding,
        )

    tune_interval = interval or config.online.tune_interval_s
    auto_apply = config.online.auto_apply

    print(f"\n{'='*60}")
    print(f"  PID Auto-Tuner - Online Mode")
    print(f"  Loop: {loop_name}")
    print(f"  Port: {serial_config.port} @ {serial_config.baudrate}")
    print(f"  Tune interval: {tune_interval}s")
    print(f"  Auto-apply: {'YES' if auto_apply else 'NO (manual confirmation)'}")
    print(f"{'='*60}\n")

    loop_config = config.get_loop(loop_name)
    current_pid = loop_config.pid

    # Load history
    history = _load_or_create_history(loop_name)

    # Setup serial
    serial_mgr = SerialManager(serial_config)
    collector = DataCollector(
        loop_name=loop_name,
        buffer_size=config.online.data_buffer_size,
    )

    try:
        serial_mgr.open()
        serial_mgr.start_reader(collector.on_serial_message)

        # Start recording to file
        record_path = collector.start_recording()
        print(f"  Recording data to: {record_path}")
        print(f"  Waiting for data from {loop_name}...\n")

        iteration = 0
        convergence_count = 0
        last_tune_time = time.time()

        while not _shutdown_requested:
            time.sleep(0.5)

            # Check if enough time has passed
            elapsed = time.time() - last_tune_time
            if elapsed < tune_interval:
                # Show status
                sys.stdout.write(
                    f"\r  [{collector.count} samples buffered] "
                    f"Next tune in {tune_interval - elapsed:.0f}s  "
                )
                sys.stdout.flush()
                continue

            # Check data availability
            samples = collector.get_recent(config.tuning.data_sample_count)
            if len(samples) < 10:
                print(f"\n  Insufficient data ({len(samples)} samples), waiting...")
                last_tune_time = time.time()
                continue

            # Time to tune!
            iteration += 1
            last_tune_time = time.time()

            if max_iterations and iteration > max_iterations:
                print(f"\n  Max iterations ({max_iterations}) reached. Stopping.")
                break

            print(f"\n\n{'─'*40}")
            print(f"  Tuning iteration #{iteration}")
            print(f"{'─'*40}")

            # Analyze
            metrics = analyze(samples)
            print(metrics.to_prompt_string())

            data_text = format_data_for_prompt(samples)

            # Call LLM
            print("\n  Consulting LLM...")
            try:
                result = tune(
                    config=config,
                    loop_name=loop_name,
                    current_pid=current_pid,
                    metrics=metrics,
                    data_text=data_text,
                    history=history,
                )
            except Exception as e:
                print(f"  ERROR: LLM call failed: {e}")
                continue

            _display_tune_result(current_pid, result, loop_name)

            # Record history
            record = create_record(
                loop_name=loop_name,
                iteration=history.iteration_count + 1,
                pid_before=current_pid.to_dict(),
                pid_after=result.new_params.to_dict(),
                metrics={
                    "overshoot_pct": metrics.overshoot_pct,
                    "settling_time_s": metrics.settling_time_s,
                    "sse_pct": metrics.steady_state_error_pct,
                },
                reason=result.reason,
                confidence=result.confidence,
                expected_improvement=result.expected_improvement,
                model_used=result.model_used,
            )
            history.add_record(record)

            # Check convergence
            if result.converged:
                convergence_count += 1
                if convergence_count >= config.tuning.convergence_patience:
                    print(
                        f"\n  Converged for {convergence_count} consecutive iterations."
                        " Stopping."
                    )
                    break
            else:
                convergence_count = 0

            # Apply new params?
            if not result.converged:
                should_apply = auto_apply
                if not auto_apply:
                    try:
                        ans = input(
                            "\n  Apply new parameters? [y/N]: "
                        ).strip().lower()
                        should_apply = ans in ("y", "yes")
                    except EOFError:
                        should_apply = False

                if should_apply:
                    print("  Sending parameters via serial...")
                    serial_mgr.send_pid(loop_name, result.new_params)

                    ack = serial_mgr.wait_for_ack(loop_name, timeout=5.0)
                    if ack:
                        print(f"  ACK received: Kp={ack.kp}, Ki={ack.ki}, Kd={ack.kd}")
                        current_pid = ack
                    else:
                        print("  WARNING: No ACK received, assuming params applied")
                        current_pid = result.new_params

                    config.update_loop_pid(loop_name, current_pid)
                else:
                    print("  Parameters NOT applied (skipped)")

            # Clear buffer for fresh data
            collector.clear()

    except Exception as e:
        print(f"\n  FATAL ERROR: {e}")
        logger.exception("Online mode error")
    finally:
        # Cleanup
        collector.stop_recording()
        serial_mgr.close()
        save_history(history)
        save_config(config)
        print("\n  Cleanup complete. History and config saved.")


# ──────────────────────────────────────────────
#  Simulate Mode (for testing without hardware)
# ──────────────────────────────────────────────

def run_simulate(
    config: AppConfig,
    loop_name: str,
    iterations: int = 5,
) -> None:
    """Run simulation mode with a software PID controller.

    Generates synthetic data using a simple plant model,
    runs PID control, then calls LLM for tuning.
    Great for testing the full pipeline without hardware.
    """
    import numpy as np

    print(f"\n{'='*60}")
    print(f"  PID Auto-Tuner - Simulation Mode")
    print(f"  Loop: {loop_name}")
    print(f"  Iterations: {iterations}")
    print(f"{'='*60}\n")

    loop_config = config.get_loop(loop_name)
    current_pid = loop_config.pid
    history = _load_or_create_history(loop_name)

    for iteration in range(1, iterations + 1):
        print(f"\n{'─'*40}")
        print(f"  Simulation iteration #{iteration}")
        print(f"  PID: Kp={current_pid.kp:.4f} Ki={current_pid.ki:.4f} Kd={current_pid.kd:.4f}")
        print(f"{'─'*40}")

        # Simulate step response
        samples = _simulate_pid_response(
            kp=current_pid.kp,
            ki=current_pid.ki,
            kd=current_pid.kd,
            target=100.0,
            dt=0.01,
            duration=2.0,
            noise_std=0.5,
        )

        # Analyze
        metrics = analyze(samples)
        print(metrics.to_prompt_string())

        data_text = format_data_for_prompt(samples)

        # Call LLM
        print("\n  Consulting LLM...")
        try:
            result = tune(
                config=config,
                loop_name=loop_name,
                current_pid=current_pid,
                metrics=metrics,
                data_text=data_text,
                history=history,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            break

        _display_tune_result(current_pid, result, loop_name)

        # Record
        record = create_record(
            loop_name=loop_name,
            iteration=history.iteration_count + 1,
            pid_before=current_pid.to_dict(),
            pid_after=result.new_params.to_dict(),
            metrics={
                "overshoot_pct": metrics.overshoot_pct,
                "settling_time_s": metrics.settling_time_s,
                "sse_pct": metrics.steady_state_error_pct,
            },
            reason=result.reason,
            confidence=result.confidence,
            expected_improvement=result.expected_improvement,
            model_used=result.model_used,
        )
        history.add_record(record)

        if result.converged:
            print("\n  LLM reports convergence. Stopping simulation.")
            break

        current_pid = result.new_params

    save_history(history)
    print("\n  Simulation complete. History saved.\n")


def _simulate_pid_response(
    kp: float,
    ki: float,
    kd: float,
    target: float,
    dt: float = 0.01,
    duration: float = 2.0,
    noise_std: float = 0.5,
) -> list[DataSample]:
    """Simulate a simple first-order + delay plant with PID control.

    Plant model: G(s) = K / (tau*s + 1) with K=1, tau=0.1s
    """
    import numpy as np

    n_steps = int(duration / dt)
    plant_tau = 0.1
    plant_k = 1.0

    actual = 0.0
    integral = 0.0
    prev_error = 0.0
    samples: list[DataSample] = []

    rng = np.random.default_rng(42)

    for i in range(n_steps):
        t = i * dt
        error = target - actual
        integral += error * dt
        derivative = (error - prev_error) / dt if dt > 0 else 0.0

        output = kp * error + ki * integral + kd * derivative
        output = max(-1000, min(1000, output))  # Output limit

        # Simple first-order plant response
        d_actual = (plant_k * output - actual) / plant_tau * dt
        actual += d_actual + rng.normal(0, noise_std) * dt

        prev_error = error

        samples.append(DataSample(
            timestamp=t,
            target=target,
            actual=actual,
            error=error,
            output=output,
        ))

    return samples


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _load_or_create_history(
    loop_name: str,
    filepath: str | None = None,
) -> TuningHistory:
    """Load existing history or create a new one."""
    if filepath:
        try:
            return load_history(filepath)
        except Exception as e:
            logger.warning("Failed to load history from %s: %s", filepath, e)

    latest = find_latest_history(loop_name)
    if latest:
        try:
            return load_history(latest)
        except Exception as e:
            logger.warning("Failed to load latest history: %s", e)

    return TuningHistory(loop_name=loop_name, records=[])


def _display_tune_result(
    current_pid: PIDParams,
    result: TuneResult,
    loop_name: str,
) -> None:
    """Display tuning result in a formatted way."""
    new = result.new_params

    print(f"\n  {'─'*30}")
    print(f"  LLM Analysis ({result.model_used}):")
    print(f"  Confidence: {result.confidence:.0%}")
    print(f"  Reason: {result.reason}")

    if result.converged:
        print(f"\n  CONVERGED - Parameters are optimal. No changes needed.")
    else:
        print(f"\n  Parameter Changes:")
        print(f"    Kp: {current_pid.kp:.6f} -> {new.kp:.6f} ({_pct_change(current_pid.kp, new.kp)})")
        print(f"    Ki: {current_pid.ki:.6f} -> {new.ki:.6f} ({_pct_change(current_pid.ki, new.ki)})")
        print(f"    Kd: {current_pid.kd:.6f} -> {new.kd:.6f} ({_pct_change(current_pid.kd, new.kd)})")
        print(f"  Expected: {result.expected_improvement}")


def _pct_change(old: float, new: float) -> str:
    """Format percentage change string."""
    if abs(old) < 1e-10:
        if abs(new) < 1e-10:
            return "no change"
        return f"+{new:.4f}"
    pct = ((new - old) / abs(old)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="PID Auto-Tuner - LLM-powered PID parameter optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Offline mode: analyze a saved CSV data file
  python main.py offline --file data/raw/speed_data.csv --loop speed

  # Online mode: real-time tuning via serial
  python main.py online --port COM3 --loop speed --interval 10

  # Simulation mode: test without hardware
  python main.py simulate --loop speed --iterations 5

Serial Protocol (MCU must implement):
  MCU -> PC:  DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>
  PC -> MCU:  PID:<loop>:<Kp>,<Ki>,<Kd>
  MCU -> PC:  ACK:<loop>:<Kp>,<Ki>,<Kd>
""",
    )

    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config.json (default: ./config.json)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="mode", help="Operating mode")

    # Offline mode
    offline = subparsers.add_parser("offline", help="Offline tuning from CSV file")
    offline.add_argument("--file", "-f", required=True, help="CSV data file path")
    offline.add_argument("--loop", "-l", required=True, help="Control loop name")
    offline.add_argument("--history", help="Previous history JSON file")

    # Online mode
    online = subparsers.add_parser("online", help="Online tuning via serial")
    online.add_argument("--loop", "-l", required=True, help="Control loop name")
    online.add_argument("--port", "-p", help="Serial port (overrides config)")
    online.add_argument("--interval", "-i", type=float, help="Tune interval (seconds)")
    online.add_argument("--max-iter", type=int, help="Max tuning iterations")

    # Simulate mode
    simulate = subparsers.add_parser("simulate", help="Simulation mode (no hardware)")
    simulate.add_argument("--loop", "-l", required=True, help="Control loop name")
    simulate.add_argument("--iterations", "-n", type=int, default=5, help="Number of iterations")

    return parser


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.mode:
        parser.print_help()
        sys.exit(0)

    # Load config
    config = load_config(args.config)

    if args.mode == "offline":
        run_offline(
            config=config,
            loop_name=args.loop,
            data_file=args.file,
            history_file=getattr(args, "history", None),
        )
    elif args.mode == "online":
        run_online(
            config=config,
            loop_name=args.loop,
            port=args.port,
            interval=args.interval,
            max_iterations=getattr(args, "max_iter", None),
        )
    elif args.mode == "simulate":
        run_simulate(
            config=config,
            loop_name=args.loop,
            iterations=args.iterations,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
