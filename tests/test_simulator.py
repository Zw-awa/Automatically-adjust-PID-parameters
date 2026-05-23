from __future__ import annotations

import unittest

from core.analyzer import DataSample
from core.data_collector import DataCollector
from core.config import PIDParams, SerialConfig
from core.serial_manager import SerialManager, parse_line
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

    def test_parse_line_understands_data_and_ack_messages(self) -> None:
        data_msg = parse_line("DATA:speed:0.1000,100.0,90.0,10.0,50.0")
        ack_msg = parse_line("ACK:speed:1.000000,0.100000,0.050000")

        self.assertEqual(data_msg.msg_type, "DATA")
        self.assertEqual(data_msg.loop_name, "speed")
        self.assertIsNotNone(data_msg.data_sample)
        self.assertEqual(data_msg.data_sample.actual, 90.0)

        self.assertEqual(ack_msg.msg_type, "ACK")
        self.assertIsNotNone(ack_msg.ack_params)
        self.assertEqual(ack_msg.ack_params.kd, 0.05)

    def test_serial_manager_can_prepare_ack_queue_before_send(self) -> None:
        mgr = SerialManager(SerialConfig(port="COM3"))
        q = mgr.prepare_ack_queue("speed")

        self.assertIs(mgr._ack_queues["speed"], q)  # type: ignore[attr-defined]

    def test_wait_for_ack_uses_prepared_queue(self) -> None:
        mgr = SerialManager(SerialConfig(port="COM3"))
        q = mgr.prepare_ack_queue("speed")
        expected = PIDParams(kp=1.0, ki=0.1, kd=0.05)
        q.put(expected)

        ack = mgr.wait_for_ack("speed", timeout=0.1, ack_queue=q)

        self.assertEqual(ack, expected)

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
