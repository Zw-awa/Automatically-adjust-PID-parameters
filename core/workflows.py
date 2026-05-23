"""Runtime workflows for Automatically-adjust-PID-parameters."""

from __future__ import annotations

import logging
import signal
import sys
import time

from core.analyzer import analyze, format_data_for_prompt, parse_csv_data
from core.config import AppConfig, PIDParams, save_config
from core.data_collector import DataCollector
from core.history_manager import (
    TuningHistory,
    create_record,
    find_latest_history,
    load_history,
    save_history,
)
from core.serial_manager import SerialManager
from core.simulator import simulate_pid_response
from core.tuner import TuneResult, tune

logger = logging.getLogger(__name__)

_shutdown_requested = False


def signal_handler(signum, frame) -> None:
    del frame
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown requested (signal %d)", signum)


def run_offline(
    config: AppConfig,
    loop_name: str,
    data_file: str,
    history_file: str | None = None,
    config_path: str | None = None,
) -> None:
    print_mode_banner(
        "Offline Mode",
        [
            f"Loop: {loop_name}",
            f"Data: {data_file}",
        ],
    )

    loop_config = config.get_loop(loop_name)

    print("[1/5] Loading data...")
    samples = parse_csv_data(data_file)
    if len(samples) < 5:
        print(f"ERROR: Only {len(samples)} samples found. Need at least 5.")
        return

    print(f"  Loaded {len(samples)} data points")

    current_pid = loop_config.pid
    metrics, data_text = analyze_samples(
        samples,
        step_label="[2/5] Analyzing performance...",
        max_rows=config.tuning.data_sample_count,
    )
    print(f"\n  Current PID: Kp={current_pid.kp}, Ki={current_pid.ki}, Kd={current_pid.kd}")

    targets_met = metrics.meets_targets(
        loop_config.target_metrics.max_overshoot_pct,
        loop_config.target_metrics.max_settling_time_s,
        loop_config.target_metrics.max_sse_pct,
    )
    if targets_met:
        print("\n  All targets met! Current parameters look good.")
        print("  Consulting LLM for verification...\n")

    print("[3/5] Loading tuning history...")
    history = load_or_create_history(loop_name, history_file)
    if history.records:
        print(f"  Found {len(history.records)} previous tuning records")
    else:
        print("  No previous history found (starting fresh)")

    result = run_tune_step(
        config=config,
        loop_name=loop_name,
        current_pid=current_pid,
        metrics=metrics,
        data_text=data_text,
        history=history,
        step_label="[4/5] Consulting LLM for parameter suggestions...",
    )
    if result is None:
        return

    display_tune_result(current_pid, result)

    record = build_tuning_record(
        loop_name=loop_name,
        iteration=history.iteration_count + 1,
        pid_before=current_pid,
        result=result,
        metrics=metrics,
        include_oscillations=True,
    )
    history.add_record(record)
    history_path = save_history(history)
    print(f"\n  History saved to: {history_path}")

    if not result.converged:
        config.update_loop_pid(loop_name, result.new_params)
        save_config(config, config_path)
        print("  Config updated with new parameters\n")

    cmd = result.new_params.format_command(loop_name)
    print(f"\n  Serial command (copy to send manually):")
    print(f"  >>> {cmd}")
    print()


def run_online(
    config: AppConfig,
    loop_name: str,
    port: str | None = None,
    interval: float | None = None,
    max_iterations: int | None = None,
    config_path: str | None = None,
) -> None:
    signal.signal(signal.SIGINT, signal_handler)
    global _shutdown_requested
    _shutdown_requested = False

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

    print_mode_banner(
        "Online Mode",
        [
            f"Loop: {loop_name}",
            f"Port: {serial_config.port} @ {serial_config.baudrate}",
            f"Tune interval: {tune_interval}s",
            f"Auto-apply: {'YES' if auto_apply else 'NO (manual confirmation)'}",
        ],
    )

    current_pid = config.get_loop(loop_name).pid
    history = load_or_create_history(loop_name)

    serial_mgr = SerialManager(serial_config)
    collector = DataCollector(loop_name=loop_name, buffer_size=config.online.data_buffer_size)

    try:
        serial_mgr.open()
        serial_mgr.start_reader(collector.on_serial_message)

        record_path = collector.start_recording()
        print(f"  Recording data to: {record_path}")
        print(f"  Waiting for data from {loop_name}...\n")

        iteration = 0
        convergence_count = 0
        last_tune_time = time.time()

        while not _shutdown_requested:
            time.sleep(0.5)

            elapsed = time.time() - last_tune_time
            if elapsed < tune_interval:
                sys.stdout.write(
                    f"\r  [{collector.count} samples buffered] "
                    f"Next tune in {tune_interval - elapsed:.0f}s  "
                )
                sys.stdout.flush()
                continue

            samples, snapshot_marker = collector.get_recent_with_marker(
                config.tuning.data_sample_count
            )
            if len(samples) < 10:
                print(f"\n  Insufficient data ({len(samples)} samples), waiting...")
                last_tune_time = time.time()
                continue

            iteration += 1
            last_tune_time = time.time()

            if max_iterations and iteration > max_iterations:
                print(f"\n  Max iterations ({max_iterations}) reached. Stopping.")
                break

            print(f"\n\n{'─'*40}")
            print(f"  Tuning iteration #{iteration}")
            print(f"{'─'*40}")

            metrics, data_text = analyze_samples(samples)

            result = run_tune_step(
                config=config,
                loop_name=loop_name,
                current_pid=current_pid,
                metrics=metrics,
                data_text=data_text,
                history=history,
            )
            if result is None:
                continue

            display_tune_result(current_pid, result)

            record = build_tuning_record(
                loop_name=loop_name,
                iteration=history.iteration_count + 1,
                pid_before=current_pid,
                result=result,
                metrics=metrics,
            )
            history.add_record(record)

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

            if not result.converged:
                should_apply = auto_apply
                if not auto_apply:
                    try:
                        ans = input("\n  Apply new parameters? [y/N]: ").strip().lower()
                        should_apply = ans in ("y", "yes")
                    except EOFError:
                        should_apply = False

                if should_apply:
                    print("  Sending parameters via serial...")
                    ack_queue = serial_mgr.prepare_ack_queue(loop_name)
                    serial_mgr.send_pid(loop_name, result.new_params)

                    ack = serial_mgr.wait_for_ack(
                        loop_name,
                        timeout=5.0,
                        ack_queue=ack_queue,
                    )
                    if ack:
                        print(f"  ACK received: Kp={ack.kp}, Ki={ack.ki}, Kd={ack.kd}")
                        current_pid = ack
                    else:
                        print("  WARNING: No ACK received, assuming params applied")
                        current_pid = result.new_params

                    config.update_loop_pid(loop_name, current_pid)
                else:
                    print("  Parameters NOT applied (skipped)")

            collector.clear_before(snapshot_marker)

    except Exception as e:
        print(f"\n  FATAL ERROR: {e}")
        logger.exception("Online mode error")
    finally:
        collector.stop_recording()
        serial_mgr.close()
        save_history(history)
        save_config(config, config_path)
        print("\n  Cleanup complete. History and config saved.")


def run_simulate(
    config: AppConfig,
    loop_name: str,
    iterations: int = 5,
) -> None:
    print_mode_banner(
        "Simulation Mode",
        [
            f"Loop: {loop_name}",
            f"Iterations: {iterations}",
        ],
    )

    loop_config = config.get_loop(loop_name)
    current_pid = loop_config.pid
    history = load_or_create_history(loop_name)

    for iteration in range(1, iterations + 1):
        print(f"\n{'─'*40}")
        print(f"  Simulation iteration #{iteration}")
        print(
            f"  PID: Kp={current_pid.kp:.4f} Ki={current_pid.ki:.4f} Kd={current_pid.kd:.4f}"
        )
        print(f"{'─'*40}")

        samples = simulate_pid_response(
            kp=current_pid.kp,
            ki=current_pid.ki,
            kd=current_pid.kd,
            target=100.0,
            dt=0.01,
            duration=2.0,
            noise_std=0.5,
        )

        metrics, data_text = analyze_samples(samples)

        result = run_tune_step(
            config=config,
            loop_name=loop_name,
            current_pid=current_pid,
            metrics=metrics,
            data_text=data_text,
            history=history,
        )
        if result is None:
            break

        display_tune_result(current_pid, result)

        record = build_tuning_record(
            loop_name=loop_name,
            iteration=history.iteration_count + 1,
            pid_before=current_pid,
            result=result,
            metrics=metrics,
        )
        history.add_record(record)

        if result.converged:
            print("\n  LLM reports convergence. Stopping simulation.")
            break

        current_pid = result.new_params

    save_history(history)
    print("\n  Simulation complete. History saved.\n")


def load_or_create_history(
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


def print_mode_banner(title: str, lines: list[str]) -> None:
    """Print a consistent banner for a workflow mode."""
    print(f"\n{'='*60}")
    print(f"  Automatically-adjust-PID-parameters - {title}")
    for line in lines:
        print(f"  {line}")
    print(f"{'='*60}\n")


def analyze_samples(
    samples,
    step_label: str | None = None,
    max_rows: int = 30,
):
    """Analyze samples and prepare prompt data text."""
    if step_label:
        print(step_label)
    metrics = analyze(samples)
    print(metrics.to_prompt_string())
    data_text = format_data_for_prompt(samples, max_rows=max_rows)
    return metrics, data_text


def run_tune_step(
    config: AppConfig,
    loop_name: str,
    current_pid: PIDParams,
    metrics,
    data_text: str,
    history: TuningHistory,
    step_label: str | None = None,
) -> TuneResult | None:
    """Run one LLM tuning step with consistent error handling."""
    if step_label:
        print(step_label)
    else:
        print("\n  Consulting LLM...")
    try:
        return tune(
            config=config,
            loop_name=loop_name,
            current_pid=current_pid,
            metrics=metrics,
            data_text=data_text,
            history=history,
        )
    except Exception as e:
        print(f"  ERROR: LLM call failed: {e}")
        if step_label:
            print("  Check your API key and network connection.")
        return None


def build_tuning_record(
    loop_name: str,
    iteration: int,
    pid_before: PIDParams,
    result: TuneResult,
    metrics,
    include_oscillations: bool = False,
):
    """Build a history record for a tuning iteration."""
    metric_data = {
        "overshoot_pct": metrics.overshoot_pct,
        "settling_time_s": metrics.settling_time_s,
        "sse_pct": metrics.steady_state_error_pct,
    }
    if include_oscillations:
        metric_data["oscillations"] = metrics.oscillation_count

    return create_record(
        loop_name=loop_name,
        iteration=iteration,
        pid_before=pid_before.to_dict(),
        pid_after=result.new_params.to_dict(),
        metrics=metric_data,
        reason=result.reason,
        confidence=result.confidence,
        expected_improvement=result.expected_improvement,
        model_used=result.model_used,
    )


def display_tune_result(current_pid: PIDParams, result: TuneResult) -> None:
    """Display tuning result in a formatted way."""
    new = result.new_params

    print(f"\n  {'─'*30}")
    print(f"  LLM Analysis ({result.model_used}):")
    print(f"  Confidence: {result.confidence:.0%}")
    print(f"  Reason: {result.reason}")

    if result.converged:
        print("\n  CONVERGED - Parameters are optimal. No changes needed.")
    else:
        print("\n  Parameter Changes:")
        print(
            f"    Kp: {current_pid.kp:.6f} -> {new.kp:.6f} "
            f"({format_pct_change(current_pid.kp, new.kp)})"
        )
        print(
            f"    Ki: {current_pid.ki:.6f} -> {new.ki:.6f} "
            f"({format_pct_change(current_pid.ki, new.ki)})"
        )
        print(
            f"    Kd: {current_pid.kd:.6f} -> {new.kd:.6f} "
            f"({format_pct_change(current_pid.kd, new.kd)})"
        )
        print(f"  Expected: {result.expected_improvement}")


def format_pct_change(old: float, new: float) -> str:
    """Format percentage change string."""
    if abs(old) < 1e-10:
        if abs(new) < 1e-10:
            return "no change"
        return f"+{new:.4f}"
    pct = ((new - old) / abs(old)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"
