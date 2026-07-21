from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import PIDParams, load_config
from experimental_lab.runner import LabRunnerManager, build_default_settings
from experimental_lab.scoring import build_default_score_weights, score_metrics
from experimental_lab.server import LabServer
from experimental_lab.storage import LabStorage
from experimental_lab.strategies import build_strategies, pick_strategy
from experimental_lab.models import MetricSnapshot, StrategyContext


class ExperimentalLabTests(unittest.TestCase):
    def test_score_metrics_marks_good_and_critical_cases(self) -> None:
        config = load_config("config.example.json")
        targets = config.get_loop("speed").target_metrics

        good = score_metrics(
            MetricSnapshot(
                overshoot_pct=1.5,
                settling_time_s=0.2,
                steady_state_error_pct=0.2,
                oscillation_count=1,
            ),
            targets,
        )
        bad = score_metrics(
            MetricSnapshot(
                overshoot_pct=20.0,
                settling_time_s=1.5,
                steady_state_error_pct=6.0,
                oscillation_count=8,
                is_diverging=True,
            ),
            targets,
        )

        self.assertTrue(good.is_good)
        self.assertEqual(good.quality_label, "good")
        self.assertFalse(bad.is_good)
        self.assertEqual(bad.quality_label, "critical")
        self.assertGreater(bad.score, good.score)

    def test_storage_session_record_delete_and_clear(self) -> None:
        config = load_config("config.example.json")
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabStorage(Path(tmp) / "lab.sqlite3")
            try:
                session = storage.create_session(
                    name="sim-one",
                    loop_name="speed",
                    mode="simulate",
                    strategy="hybrid",
                    settings=build_default_settings(config, loop_name="speed", mode="simulate", strategy="hybrid"),
                )

                metrics = MetricSnapshot(
                    overshoot_pct=2.0,
                    settling_time_s=0.3,
                    steady_state_error_pct=0.4,
                    oscillation_count=1,
                )
                first = storage.add_record(
                    session_id=session.id,
                    iteration_index=1,
                    source="manual",
                    applied=True,
                    strategy_name="hybrid",
                    model_used="manual-entry",
                    prev_pid=session.current_pid,
                    pid=PIDParams(kp=1.1, ki=0.11, kd=0.051),
                    metrics=metrics,
                    score=12.0,
                    is_good=True,
                    quality_label="good",
                    note="keep",
                )
                second = storage.add_record(
                    session_id=session.id,
                    iteration_index=2,
                    source="manual",
                    applied=True,
                    strategy_name="hybrid",
                    model_used="manual-entry",
                    prev_pid=first.pid,
                    pid=PIDParams(kp=1.12, ki=0.12, kd=0.055),
                    metrics=metrics,
                    score=11.5,
                    is_good=True,
                    quality_label="good",
                    note="delete me",
                )

                self.assertEqual(len(storage.list_records(session.id)), 2)
                deleted_session_id = storage.delete_record(second.id)
                self.assertEqual(deleted_session_id, session.id)
                self.assertEqual(len(storage.list_records(session.id)), 1)

                storage.clear_records(session.id)
                self.assertEqual(len(storage.list_records(session.id)), 0)
                same_session = storage.get_session(session.id)
                self.assertEqual(same_session.name, "sim-one")
            finally:
                storage.close()

    def test_hybrid_strategy_falls_back_to_llm_then_bo(self) -> None:
        config = load_config("config.example.json")
        bundle = build_strategies(config)
        hybrid = pick_strategy(bundle, "hybrid")
        settings = build_default_settings(config, loop_name="speed", mode="simulate", strategy="hybrid")
        current_pid = config.get_loop("speed").pid
        metrics = MetricSnapshot(
            overshoot_pct=8.0,
            settling_time_s=0.8,
            steady_state_error_pct=2.0,
            oscillation_count=2,
        )

        cold_context = StrategyContext(
            session_id=1,
            loop_name="speed",
            mode="simulate",
            strategy_name="hybrid",
            current_pid=current_pid,
            previous_pid=current_pid,
            metrics=metrics,
            data_text="sample data",
            settings=settings,
            records=[],
        )
        with mock.patch("experimental_lab.strategies.tune") as mock_tune:
            mock_result = mock.Mock()
            mock_result.new_params = PIDParams(kp=1.2, ki=0.12, kd=0.055)
            mock_result.reason = "LLM cold start"
            mock_result.confidence = 0.8
            mock_result.expected_improvement = "faster response"
            mock_result.converged = False
            mock_result.model_used = "mock-llm"
            mock_tune.return_value = mock_result
            suggestion = hybrid.suggest(cold_context)
        self.assertEqual(suggestion.metadata["phase"], "cold-start")
        self.assertEqual(suggestion.model_used, "mock-llm")

        records = []
        for index in range(1, 4):
            records.append(
                type("Record", (), {
                    "id": index,
                    "session_id": 1,
                    "iteration_index": index,
                    "source": "auto",
                    "applied": True,
                    "strategy_name": "hybrid",
                    "model_used": "simulation-observed",
                    "prev_pid": current_pid,
                    "pid": PIDParams(kp=1.0 + index * 0.02, ki=0.1 + index * 0.01, kd=0.05 + index * 0.004),
                    "metrics": metrics,
                    "score": 30.0 - index,
                    "is_good": False,
                    "quality_label": "watch",
                    "reason": "seed",
                    "confidence": 1.0,
                    "expected_improvement": "",
                    "raw_data_path": None,
                    "note": "",
                    "strategy_metadata": {},
                    "created_at": "2026-01-01T00:00:00Z",
                })()
            )
        bo_context = StrategyContext(
            session_id=1,
            loop_name="speed",
            mode="simulate",
            strategy_name="hybrid",
            current_pid=current_pid,
            previous_pid=current_pid,
            metrics=metrics,
            data_text="sample data",
            settings=settings,
            records=records,
        )
        suggestion = hybrid.suggest(bo_context)
        self.assertEqual(suggestion.metadata["phase"], "bo")
        self.assertEqual(suggestion.metadata["source"], "bo")

    def test_simulation_runner_persists_records(self) -> None:
        config = load_config("config.example.json")
        published: list[tuple[int, str, dict[str, object]]] = []
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabStorage(Path(tmp) / "lab.sqlite3")
            try:
                settings = build_default_settings(
                    config,
                    loop_name="speed",
                    mode="simulate",
                    strategy="bo",
                    overrides={"max_iterations": 2, "simulate_noise_std": 0.0},
                )
                session = storage.create_session(
                    name="sim-run",
                    loop_name="speed",
                    mode="simulate",
                    strategy="bo",
                    settings=settings,
                )
                manager = LabRunnerManager(storage, config, publish=lambda sid, event, payload: published.append((sid, event, payload)))
                with mock.patch(
                    "experimental_lab.runner.LAB_RAW_DATA_DIR",
                    Path(tmp) / "raw",
                ):
                    manager.start(session.id)

                    for _ in range(100):
                        snapshot = storage.get_session(session.id)
                        if snapshot.status in ("completed", "failed"):
                            break
                        import time
                        time.sleep(0.05)

                records = storage.list_records(session.id)
                self.assertGreaterEqual(len(records), 1)
                self.assertTrue(any(event == "record.added" for _, event, _ in published))
            finally:
                storage.close()

    def test_server_health_and_session_endpoints(self) -> None:
        config = load_config("config.example.json")
        with tempfile.TemporaryDirectory() as tmp:
            server = LabServer(host="127.0.0.1", port=0, config=config, db_path=str(Path(tmp) / "lab.sqlite3"))
            thread = server.start_in_thread()
            self.assertTrue(thread.is_alive())
            import urllib.request

            base = f"http://127.0.0.1:{server.port}"
            with urllib.request.urlopen(f"{base}/api/health") as response:
                health = response.read().decode("utf-8")
            self.assertIn('"ok": true', health)

            request = urllib.request.Request(
                f"{base}/api/sessions",
                data=(
                    '{"name":"server-test","loop_name":"speed","mode":"simulate","strategy":"hybrid"}'
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                created = response.read().decode("utf-8")
            self.assertIn('"server-test"', created)
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
