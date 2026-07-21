from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.analyzer import DataQualityError, DataSample, analyze, parse_csv_data
from core.config import load_config, save_config
from core.workflows import run_offline


class SystemTests(unittest.TestCase):
    def test_analyze_rejects_insufficient_samples(self) -> None:
        samples = [DataSample(0.0, 1.0, 0.0, 1.0, 0.0)]
        with self.assertRaisesRegex(DataQualityError, "insufficient samples"):
            analyze(samples)

    def test_analyze_rejects_invalid_trace_values(self) -> None:
        samples = [
            DataSample(index * 0.1, 1.0, 0.5, 0.5, 0.2)
            for index in range(10)
        ]
        samples[5] = DataSample(0.5, 1.0, 0.5, float("nan"), 0.2)
        with self.assertRaisesRegex(DataQualityError, "NaN"):
            analyze(samples)
    def test_parse_example_csv_and_analyze(self) -> None:
        samples = parse_csv_data("data/raw/example_speed_data.csv")
        metrics = analyze(samples)

        self.assertEqual(len(samples), 51)
        self.assertGreater(metrics.overshoot_pct, 0)
        self.assertGreater(metrics.settling_time_s, 0)
        self.assertEqual(metrics.data_points, 51)

    def test_load_config_falls_back_to_example_when_local_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_local = Path(tmp) / "config.json"
            with mock.patch("core.config.DEFAULT_CONFIG_PATH", missing_local):
                with mock.patch("core.config.EXAMPLE_CONFIG_PATH", Path("config.example.json")):
                    config = load_config()

        self.assertEqual(config.get_loop("speed").pid.kp, 1.0)
        self.assertEqual(config.llm.model, "deepseek-reasoner")

    def test_save_config_preserves_existing_local_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                """
{
  "llm": {
    "api_key": "local-secret-key"
  }
}
""".strip(),
                encoding="utf-8",
            )

            config = load_config("config.example.json")
            save_config(config, config_path)
            saved = config_path.read_text(encoding="utf-8")

        self.assertIn("local-secret-key", saved)

    def test_run_offline_saves_back_to_explicit_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "custom-config.json"
            history_path = Path(tmp) / "history.json"
            config_path.write_text(Path("config.example.json").read_text(encoding="utf-8"), encoding="utf-8")

            config = load_config(config_path)

            fake_result = mock.Mock()
            fake_result.new_params = config.get_loop("speed").pid
            fake_result.reason = "ok"
            fake_result.confidence = 0.9
            fake_result.expected_improvement = "ok"
            fake_result.model_used = "mock"
            fake_result.converged = False

            history_path.write_text(
                '{"loop_name": "speed", "record_count": 0, "records": []}',
                encoding="utf-8",
            )

            with mock.patch("core.workflows.tune", return_value=fake_result):
                run_offline(
                    config=config,
                    loop_name="speed",
                    data_file="data/raw/example_speed_data.csv",
                    history_file=str(history_path),
                    config_path=str(config_path),
                )

            self.assertTrue(config_path.exists())
            saved_history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_history["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
