"""Simulation helpers for Automatically-adjust-PID-parameters."""

from __future__ import annotations

from core.analyzer import DataSample


def simulate_pid_response(
    kp: float,
    ki: float,
    kd: float,
    target: float,
    dt: float = 0.01,
    duration: float = 2.0,
    noise_std: float = 0.5,
) -> list[DataSample]:
    """Simulate a simple first-order + delay plant with PID control."""
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
        output = max(-1000, min(1000, output))

        # A sample represents one instant: actual and error must come from the
        # same plant state. Advance the plant only after recording that sample.
        samples.append(
            DataSample(
                timestamp=t,
                target=target,
                actual=actual,
                error=error,
                output=output,
            )
        )

        d_actual = (plant_k * output - actual) / plant_tau * dt
        actual += d_actual + rng.normal(0, noise_std) * dt
        prev_error = error

    return samples
