"""Session runners for the experimental lab."""

from __future__ import annotations

import csv
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.analyzer import analyze, format_data_for_prompt, parse_csv_data
from core.config import AppConfig, PIDParams
from core.simulator import simulate_pid_response
from experimental_lab.models import MetricSnapshot, StrategyContext
from experimental_lab.scoring import build_default_score_weights, score_metrics
from experimental_lab.storage import LabStorage
from experimental_lab.strategies import StrategyBundle, build_strategies, pick_strategy

logger = logging.getLogger(__name__)

PublishFn = Callable[[int, str, dict[str, Any]], None]

LAB_RAW_DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "lab"


def build_default_settings(
    config: AppConfig,
    *,
    loop_name: str,
    mode: str,
    strategy: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build persisted session settings with sensible defaults."""
    loop = config.get_loop(loop_name)
    settings: dict[str, Any] = {
        "loop_name": loop_name,
        "mode": mode,
        "strategy": strategy,
        "current_pid": loop.pid.to_dict(),
        "target_metrics": {
            "max_overshoot_pct": loop.target_metrics.max_overshoot_pct,
            "max_settling_time_s": loop.target_metrics.max_settling_time_s,
            "max_sse_pct": loop.target_metrics.max_sse_pct,
        },
        "score_weights": build_default_score_weights(),
        "data_sample_count": config.tuning.data_sample_count,
        "max_iterations": 5,
        "simulate_target": 100.0,
        "simulate_dt": 0.01,
        "simulate_duration": 2.0,
        "simulate_noise_std": 0.5,
        "offline_file": "",
        "last_suggestion": None,
    }
    if overrides:
        settings.update(overrides)
    return settings


@dataclass
class SessionWorker:
    """Thread-backed worker for a single session."""

    session_id: int
    stop_event: threading.Event
    resume_event: threading.Event
    thread: threading.Thread


class LabRunnerManager:
    """Manage start, stop, pause, and resume for lab sessions."""

    def __init__(self, storage: LabStorage, config: AppConfig, publish: PublishFn) -> None:
        self._storage = storage
        self._config = config
        self._publish = publish
        self._strategies: StrategyBundle = build_strategies(config)
        self._workers: dict[int, SessionWorker] = {}
        self._lock = threading.Lock()

    def start(self, session_id: int) -> None:
        with self._lock:
            worker = self._workers.get(session_id)
            if worker and worker.thread.is_alive():
                raise RuntimeError("Session is already running")

            stop_event = threading.Event()
            resume_event = threading.Event()
            resume_event.set()
            thread = threading.Thread(
                target=self._run_session,
                args=(session_id, stop_event, resume_event),
                name=f"lab-session-{session_id}",
                daemon=True,
            )
            self._workers[session_id] = SessionWorker(
                session_id=session_id,
                stop_event=stop_event,
                resume_event=resume_event,
                thread=thread,
            )
            thread.start()

    def pause(self, session_id: int) -> None:
        with self._lock:
            worker = self._workers.get(session_id)
            if not worker or not worker.thread.is_alive():
                raise RuntimeError("Session is not running")
            worker.resume_event.clear()
        session = self._storage.update_session(session_id, status="paused")
        self._publish(session_id, "session.updated", {"session": session.to_dict()})

    def resume(self, session_id: int) -> None:
        with self._lock:
            worker = self._workers.get(session_id)
            if not worker or not worker.thread.is_alive():
                raise RuntimeError("Session is not running")
            worker.resume_event.set()
        session = self._storage.update_session(session_id, status="running")
        self._publish(session_id, "session.updated", {"session": session.to_dict()})

    def stop(self, session_id: int) -> None:
        with self._lock:
            worker = self._workers.get(session_id)
            if not worker or not worker.thread.is_alive():
                raise RuntimeError("Session is not running")
            worker.stop_event.set()
            worker.resume_event.set()

    def _run_session(
        self,
        session_id: int,
        stop_event: threading.Event,
        resume_event: threading.Event,
    ) -> None:
        try:
            session = self._storage.get_session(session_id)
            session = self._storage.update_session(session_id, status="running")
            self._publish(session_id, "session.updated", {"session": session.to_dict()})
            if session.mode == "simulate":
                self._run_simulation(session_id, stop_event, resume_event)
            elif session.mode == "offline":
                self._run_offline(session_id)
            else:
                raise ValueError(f"Unsupported lab mode: {session.mode}")
            final = self._storage.get_session(session_id)
            if final.status not in ("completed", "failed"):
                final = self._storage.update_session(session_id, status="completed")
            self._publish(session_id, "run.completed", {"session": final.to_dict()})
        except Exception as exc:
            logger.exception("Lab session %s failed", session_id)
            failed = self._storage.update_session(session_id, status="failed")
            self._publish(
                session_id,
                "run.failed",
                {"session": failed.to_dict(), "error": str(exc)},
            )
        finally:
            with self._lock:
                self._workers.pop(session_id, None)

    def _run_simulation(
        self,
        session_id: int,
        stop_event: threading.Event,
        resume_event: threading.Event,
    ) -> None:
        session = self._storage.get_session(session_id)
        settings = dict(session.settings)
        max_iterations = int(settings.get("max_iterations", 5))
        current_pid = PIDParams(**settings.get("current_pid", {}))
        previous_pid = current_pid

        for _ in range(max_iterations):
            if stop_event.is_set():
                stopped = self._storage.update_session(session_id, status="completed")
                self._publish(
                    session_id,
                    "run.stage",
                    {"stage": "stopped", "session": stopped.to_dict()},
                )
                return
            while not resume_event.is_set():
                if stop_event.is_set():
                    return
                time.sleep(0.1)

            iteration = self._storage.next_iteration_index(session_id)
            self._publish(
                session_id,
                "run.stage",
                {"stage": "simulating", "iteration": iteration},
            )
            samples = simulate_pid_response(
                kp=current_pid.kp,
                ki=current_pid.ki,
                kd=current_pid.kd,
                target=float(settings.get("simulate_target", 100.0)),
                dt=float(settings.get("simulate_dt", 0.01)),
                duration=float(settings.get("simulate_duration", 2.0)),
                noise_std=float(settings.get("simulate_noise_std", 0.5)),
            )
            raw_path = self._write_samples(session_id, iteration, samples)

            self._publish(
                session_id,
                "run.stage",
                {"stage": "analyzing", "iteration": iteration},
            )
            metrics = analyze(samples, output_limits=(-1000.0, 1000.0))
            snapshot = MetricSnapshot.from_performance_metrics(metrics)
            score = score_metrics(
                snapshot,
                self._config.get_loop(session.loop_name).target_metrics,
                weights=settings.get("score_weights"),
            )
            data_text = format_data_for_prompt(
                samples, max_rows=int(settings.get("data_sample_count", 50))
            )
            record = self._storage.add_record(
                session_id=session_id,
                iteration_index=iteration,
                source="auto",
                applied=True,
                strategy_name=session.strategy,
                model_used="simulation-observed",
                prev_pid=previous_pid,
                pid=current_pid,
                metrics=snapshot,
                score=score.score,
                is_good=score.is_good,
                quality_label=score.quality_label,
                reason="Observed simulation response",
                confidence=1.0,
                expected_improvement="Measured from the simulated plant.",
                raw_data_path=str(raw_path),
                note="",
                strategy_metadata={"score_breakdown": score.breakdown},
            )
            self._publish(session_id, "record.added", {"record": record.to_dict()})

            if score.is_good or iteration >= max_iterations:
                updated = dict(settings)
                updated["current_pid"] = current_pid.to_dict()
                updated["last_suggestion"] = None
                self._storage.update_session(session_id, settings=updated, status="completed")
                return

            context = StrategyContext(
                session_id=session_id,
                loop_name=session.loop_name,
                mode=session.mode,
                strategy_name=session.strategy,
                current_pid=current_pid,
                previous_pid=previous_pid,
                metrics=snapshot,
                data_text=data_text,
                settings=settings,
                records=self._storage.list_records(session_id),
            )
            self._publish(
                session_id,
                "run.stage",
                {"stage": "strategy_proposing", "iteration": iteration},
            )
            suggestion = pick_strategy(self._strategies, session.strategy).suggest(context)
            settings["last_suggestion"] = suggestion.to_dict()
            settings["current_pid"] = suggestion.pid.to_dict()
            self._storage.update_session(session_id, settings=settings, status="running")
            self._publish(
                session_id,
                "run.suggestion",
                {"iteration": iteration, "suggestion": suggestion.to_dict()},
            )

            if suggestion.converged:
                self._storage.update_session(session_id, settings=settings, status="completed")
                return

            previous_pid = current_pid
            current_pid = suggestion.pid

    def _run_offline(self, session_id: int) -> None:
        session = self._storage.get_session(session_id)
        settings = dict(session.settings)
        filepath = str(settings.get("offline_file", "")).strip()
        if not filepath:
            raise ValueError("Offline session is missing offline_file")

        iteration = self._storage.next_iteration_index(session_id)
        self._publish(session_id, "run.stage", {"stage": "loading_file", "iteration": iteration})
        samples = parse_csv_data(filepath)
        if len(samples) < 5:
            raise ValueError("Offline file must contain at least 5 samples")

        metrics = analyze(samples)
        snapshot = MetricSnapshot.from_performance_metrics(metrics)
        score = score_metrics(
            snapshot,
            self._config.get_loop(session.loop_name).target_metrics,
            weights=settings.get("score_weights"),
        )
        data_text = format_data_for_prompt(
            samples, max_rows=int(settings.get("data_sample_count", 50))
        )
        current_pid = PIDParams(**settings.get("current_pid", {}))
        record = self._storage.add_record(
            session_id=session_id,
            iteration_index=iteration,
            source="auto",
            applied=True,
            strategy_name=session.strategy,
            model_used="offline-observed",
            prev_pid=current_pid,
            pid=current_pid,
            metrics=snapshot,
            score=score.score,
            is_good=score.is_good,
            quality_label=score.quality_label,
            reason="Observed offline dataset",
            confidence=1.0,
            expected_improvement="Baseline imported from offline CSV.",
            raw_data_path=filepath,
            note="",
            strategy_metadata={"score_breakdown": score.breakdown},
        )
        self._publish(session_id, "record.added", {"record": record.to_dict()})

        context = StrategyContext(
            session_id=session_id,
            loop_name=session.loop_name,
            mode=session.mode,
            strategy_name=session.strategy,
            current_pid=current_pid,
            previous_pid=current_pid,
            metrics=snapshot,
            data_text=data_text,
            settings=settings,
            records=self._storage.list_records(session_id),
        )
        suggestion = pick_strategy(self._strategies, session.strategy).suggest(context)
        settings["last_suggestion"] = suggestion.to_dict()
        settings["current_pid"] = suggestion.pid.to_dict()
        updated = self._storage.update_session(session_id, settings=settings, status="completed")
        self._publish(
            session_id,
            "run.suggestion",
            {"iteration": iteration, "suggestion": suggestion.to_dict(), "session": updated.to_dict()},
        )

    def _write_samples(self, session_id: int, iteration: int, samples: list[Any]) -> Path:
        LAB_RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        session_dir = LAB_RAW_DATA_DIR / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        filepath = session_dir / f"iteration_{iteration:03d}.csv"
        with open(filepath, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "target", "actual", "error", "output"])
            for sample in samples:
                writer.writerow(
                    [
                        f"{sample.timestamp:.6f}",
                        f"{sample.target:.4f}",
                        f"{sample.actual:.4f}",
                        f"{sample.error:.4f}",
                        f"{sample.output:.4f}",
                    ]
                )
        return filepath
