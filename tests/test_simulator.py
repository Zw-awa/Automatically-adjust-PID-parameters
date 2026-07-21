from __future__ import annotations

import unittest

from core.analyzer import DataSample
from core.data_collector import DataCollector
from core.config import PIDParams, SerialConfig
from core.serial_manager import (
    ParsedMessage,
    SerialManager,
    format_pid_command,
    parse_line,
)
from core.simulator import simulate_pid_response


class SimulatorTests(unittest.TestCase):
    def test_simulator_generates_expected_number_of_samples(self) -> None:
        samples = simulate_pid_response(
            kp=1.0,
            ki=0.1,
            kd=0.05,
            target=100.0,
            dt=0.01,
            duration=1.0,
            noise_std=0.0,
        )

        self.assertEqual(len(samples), 100)
        self.assertEqual(samples[0].timestamp, 0.0)
        self.assertEqual(samples[-1].timestamp, 0.99)
        for sample in samples:
            self.assertAlmostEqual(sample.error, sample.target - sample.actual)

    def test_parse_line_understands_data_and_ack_messages(self) -> None:
        data_msg = parse_line("DATA:speed:0.1000,100.0,90.0,10.0,50.0")
        ack_msg = parse_line("ACK:req123:speed:1.000000,0.100000,0.050000")

        self.assertEqual(data_msg.msg_type, "DATA")
        self.assertEqual(data_msg.loop_name, "speed")
        self.assertIsNotNone(data_msg.data_sample)
        self.assertEqual(data_msg.data_sample.actual, 90.0)

        self.assertEqual(ack_msg.msg_type, "ACK")
        self.assertEqual(ack_msg.request_id, "req123")
        self.assertIsNotNone(ack_msg.ack_params)
        self.assertEqual(ack_msg.ack_params.kd, 0.05)

    def test_format_pid_command_uses_protocol_v2(self) -> None:
        command = format_pid_command(
            "speed",
            PIDParams(kp=1.0, ki=0.1, kd=0.05),
            request_id="req123",
        )

        self.assertEqual(
            command,
            "PID:req123:speed:1.000000,0.100000,0.050000",
        )

    def test_serial_manager_can_prepare_ack_queue_before_send(self) -> None:
        mgr = SerialManager(SerialConfig(port="COM3"))
        q = mgr.prepare_ack_queue("req123")

        self.assertIs(mgr._ack_queues["req123"], q)  # type: ignore[attr-defined]

    def test_wait_for_ack_uses_prepared_queue(self) -> None:
        mgr = SerialManager(SerialConfig(port="COM3"))
        q = mgr.prepare_ack_queue("req123")
        expected = PIDParams(kp=1.0, ki=0.1, kd=0.05)
        q.put(ParsedMessage(
            msg_type="ACK",
            loop_name="speed",
            payload="1.0,0.1,0.05",
            ack_params=expected,
            request_id="req123",
        ))

        ack = mgr.wait_for_ack(
            "req123",
            "speed",
            expected,
            timeout=0.1,
            ack_queue=q,
        )

        self.assertEqual(ack, expected)

    def test_wait_for_ack_rejects_mismatched_parameters(self) -> None:
        mgr = SerialManager(SerialConfig(port="COM3"))
        q = mgr.prepare_ack_queue("req123")
        q.put(parse_line("ACK:req123:speed:2.0,0.1,0.05"))

        with self.assertRaisesRegex(RuntimeError, "do not match"):
            mgr.wait_for_ack(
                "req123",
                "speed",
                PIDParams(kp=1.0, ki=0.1, kd=0.05),
                timeout=0.1,
                ack_queue=q,
            )

    def test_parse_line_understands_nack(self) -> None:
        message = parse_line("NACK:req123:speed:OUT_OF_RANGE:kp")
        self.assertEqual(message.msg_type, "NACK")
        self.assertEqual(message.request_id, "req123")
        self.assertEqual(message.error_code, "OUT_OF_RANGE")

    def test_data_collector_clear_before_keeps_new_samples(self) -> None:
        collector = DataCollector(loop_name="speed", buffer_size=10)

        for idx in range(5):
            collector.add_sample(
                DataSample(
                    timestamp=float(idx),
                    target=100.0,
                    actual=95.0,
                    error=5.0,
                    output=50.0,
                )
            )

        samples, marker = collector.get_recent_with_marker(5)
        self.assertEqual(len(samples), 5)

        for idx in range(5, 8):
            collector.add_sample(
                DataSample(
                    timestamp=float(idx),
                    target=100.0,
                    actual=96.0,
                    error=4.0,
                    output=51.0,
                )
            )

        collector.clear_before(marker)
        remaining = collector.get_all()

        self.assertEqual(len(remaining), 3)
        self.assertEqual([s.timestamp for s in remaining], [5.0, 6.0, 7.0])


if __name__ == "__main__":
    unittest.main()
