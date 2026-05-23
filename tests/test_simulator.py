from __future__ import annotations

import unittest

from main import _simulate_pid_response
from core.serial_manager import parse_line


class SimulatorTests(unittest.TestCase):
    def test_simulator_generates_expected_number_of_samples(self) -> None:
        samples = _simulate_pid_response(
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


if __name__ == "__main__":
    unittest.main()
