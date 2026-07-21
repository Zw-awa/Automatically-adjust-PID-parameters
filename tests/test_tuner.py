from __future__ import annotations

import unittest
from unittest import mock

from core.analyzer import PerformanceMetrics
from core.config import PIDParams, load_config
from core.history_manager import TuningHistory
from core.tuner import build_system_prompt, parse_response, tune, validate_change


class TunerTests(unittest.TestCase):
    def test_parse_response_accepts_json_code_block(self) -> None:
        raw = """```json
        {
          "kp": 1.2,
          "ki": 0.15,
          "kd": 0.04,
          "reason": "reduce overshoot",
          "confidence": 0.88,
          "expected_improvement": "lower overshoot",
          "converged": false
        }
        ```"""

        parsed = parse_response(raw)

        self.assertEqual(parsed["kp"], 1.2)
        self.assertFalse(parsed["converged"])

    def test_validate_change_clamps_large_step(self) -> None:
        config = load_config("config.example.json")
        loop_config = config.get_loop("speed")
        current = PIDParams(kp=1.0, ki=0.1, kd=0.05)
        proposed = PIDParams(kp=3.0, ki=1.0, kd=0.5)

        validated = validate_change(current, proposed, config.tuning, loop_config)

        self.assertAlmostEqual(validated.kp, 1.2)
        self.assertAlmostEqual(validated.ki, 0.12)
        self.assertAlmostEqual(validated.kd, 0.06)

    def test_validate_change_snaps_small_changes(self) -> None:
        config = load_config("config.example.json")
        loop_config = config.get_loop("speed")
        current = PIDParams(kp=1.0, ki=0.1, kd=0.05)
        proposed = PIDParams(kp=1.005, ki=0.105, kd=0.055)

        validated = validate_change(current, proposed, config.tuning, loop_config)

        self.assertEqual(validated, current)

    def test_build_system_prompt_uses_change_limit(self) -> None:
        config = load_config("config.example.json")
        prompt = build_system_prompt(config.tuning)
        self.assertIn("20%", prompt)

    def test_tune_uses_fallback_and_respects_converged(self) -> None:
        config = load_config("config.example.json")
        metrics = PerformanceMetrics(
            overshoot_pct=1.0,
            settling_time_s=0.1,
            steady_state_error_pct=0.1,
            rise_time_s=0.05,
            oscillation_count=0,
            peak_error=1.0,
            mean_abs_error=0.2,
            rms_error=0.3,
            is_diverging=False,
            is_saturated=False,
            data_points=20,
        )

        calls: list[bool] = []

        def fake_call_llm(*args, **kwargs) -> str:
            use_fallback = kwargs.get("use_fallback", False)
            calls.append(use_fallback)
            if not use_fallback:
                raise RuntimeError("primary failed")
            return """{
              "kp": 2.0,
              "ki": 0.5,
              "kd": 0.1,
              "reason": "already good",
              "confidence": 0.91,
              "expected_improvement": "keep stable",
              "converged": true
            }"""

        with mock.patch("core.tuner.call_llm", side_effect=fake_call_llm):
            result = tune(
                config=config,
                loop_name="speed",
                current_pid=config.get_loop("speed").pid,
                metrics=metrics,
                data_text="sample data",
                history=TuningHistory(loop_name="speed", records=[]),
            )

        self.assertEqual(calls, [False, True])
        self.assertTrue(result.converged)
        self.assertEqual(result.new_params, config.get_loop("speed").pid)
        self.assertEqual(result.model_used, config.llm.model_fallback)


if __name__ == "__main__":
    unittest.main()
