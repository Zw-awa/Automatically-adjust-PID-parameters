from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.analyzer import analyze, parse_csv_data
from core.config import load_config, save_config


class SystemTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
