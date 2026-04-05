"""Configuration management for PID Auto-Tuner.

Loads, validates, and provides access to all configuration settings.
Supports multiple control loops (speed, steering, position, current).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default config path (project root)
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.json"


@dataclass(frozen=True)
class SerialConfig:
    """Serial port configuration."""

    port: str = "COM3"
    baudrate: int = 115200
    timeout: float = 1.0
    encoding: str = "utf-8"


@dataclass(frozen=True)
class LLMConfig:
    """LLM API configuration (DeepSeek-compatible).

    API key is read from DEEPSEEK_API_KEY env var by default.
    Falls back to config.json value if env var is not set.
    """

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-reasoner"
    model_fallback: str = "deepseek-chat"
    temperature: float = 0.3
    max_tokens: int = 1024


@dataclass(frozen=True)
class PIDParams:
    """A set of PID parameters."""

    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.05

    def to_dict(self) -> dict[str, float]:
        return {"kp": self.kp, "ki": self.ki, "kd": self.kd}

    def format_command(self, loop_name: str) -> str:
        """Format as serial command: PID:loop:Kp,Ki,Kd"""
        return f"PID:{loop_name}:{self.kp:.6f},{self.ki:.6f},{self.kd:.6f}"


@dataclass(frozen=True)
class ParamLimits:
    """Safety limits for PID parameters."""

    kp_min: float = 0.01
    kp_max: float = 50.0
    ki_min: float = 0.0
    ki_max: float = 20.0
    kd_min: float = 0.0
    kd_max: float = 10.0

    def clamp(self, params: PIDParams) -> PIDParams:
        """Clamp PID parameters to within safety limits."""
        return PIDParams(
            kp=max(self.kp_min, min(self.kp_max, params.kp)),
            ki=max(self.ki_min, min(self.ki_max, params.ki)),
            kd=max(self.kd_min, min(self.kd_max, params.kd)),
        )


@dataclass(frozen=True)
class TargetMetrics:
    """Target performance metrics for a control loop."""

    max_overshoot_pct: float = 5.0
    max_settling_time_s: float = 0.5
    max_sse_pct: float = 1.0


@dataclass(frozen=True)
class LoopConfig:
    """Configuration for a single control loop."""

    name: str
    pid: PIDParams
    limits: ParamLimits
    target_metrics: TargetMetrics
    description: str = ""


@dataclass(frozen=True)
class TuningConfig:
    """Tuning behavior configuration."""

    max_change_ratio: float = 0.2
    min_change_threshold: float = 0.01
    history_window: int = 10
    data_sample_count: int = 50
    convergence_patience: int = 3


@dataclass(frozen=True)
class OnlineConfig:
    """Online (real-time) tuning configuration."""

    tune_interval_s: float = 10.0
    data_buffer_size: int = 200
    auto_apply: bool = False


@dataclass
class AppConfig:
    """Top-level application configuration."""

    serial: SerialConfig = field(default_factory=SerialConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    loops: dict[str, LoopConfig] = field(default_factory=dict)
    tuning: TuningConfig = field(default_factory=TuningConfig)
    online: OnlineConfig = field(default_factory=OnlineConfig)

    def get_loop(self, loop_name: str) -> LoopConfig:
        """Get configuration for a specific control loop."""
        if loop_name not in self.loops:
            available = ", ".join(self.loops.keys())
            raise ValueError(
                f"Unknown loop '{loop_name}'. Available: {available}"
            )
        return self.loops[loop_name]

    def update_loop_pid(self, loop_name: str, new_pid: PIDParams) -> None:
        """Update PID parameters for a loop (clamped to limits)."""
        loop = self.get_loop(loop_name)
        clamped = loop.limits.clamp(new_pid)
        self.loops[loop_name] = LoopConfig(
            name=loop.name,
            pid=clamped,
            limits=loop.limits,
            target_metrics=loop.target_metrics,
            description=loop.description,
        )


def _parse_loop_config(name: str, raw: dict[str, Any]) -> LoopConfig:
    """Parse a single loop configuration from raw dict."""
    pid_raw = raw.get("pid", {})
    limits_raw = raw.get("limits", {})
    metrics_raw = raw.get("target_metrics", {})

    return LoopConfig(
        name=raw.get("name", name),
        pid=PIDParams(
            kp=pid_raw.get("kp", 1.0),
            ki=pid_raw.get("ki", 0.1),
            kd=pid_raw.get("kd", 0.05),
        ),
        limits=ParamLimits(
            kp_min=limits_raw.get("kp", [0.01, 50.0])[0],
            kp_max=limits_raw.get("kp", [0.01, 50.0])[1],
            ki_min=limits_raw.get("ki", [0.0, 20.0])[0],
            ki_max=limits_raw.get("ki", [0.0, 20.0])[1],
            kd_min=limits_raw.get("kd", [0.0, 10.0])[0],
            kd_max=limits_raw.get("kd", [0.0, 10.0])[1],
        ),
        target_metrics=TargetMetrics(
            max_overshoot_pct=metrics_raw.get("max_overshoot_pct", 5.0),
            max_settling_time_s=metrics_raw.get("max_settling_time_s", 0.5),
            max_sse_pct=metrics_raw.get("max_sse_pct", 1.0),
        ),
        description=raw.get("description", ""),
    )


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load configuration from JSON file.

    Args:
        path: Path to config file. Uses DEFAULT_CONFIG_PATH if None.

    Returns:
        Parsed AppConfig object.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.warning("Config file not found at %s, using defaults", config_path)
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    serial_raw = raw.get("serial", {})
    llm_raw = raw.get("llm", {})
    tuning_raw = raw.get("tuning", {})
    online_raw = raw.get("online", {})
    loops_raw = raw.get("loops", {})

    loops = {
        name: _parse_loop_config(name, loop_data)
        for name, loop_data in loops_raw.items()
    }

    return AppConfig(
        serial=SerialConfig(
            port=serial_raw.get("port", "COM3"),
            baudrate=serial_raw.get("baudrate", 115200),
            timeout=serial_raw.get("timeout", 1.0),
            encoding=serial_raw.get("encoding", "utf-8"),
        ),
        llm=LLMConfig(
            api_key=os.environ.get("DEEPSEEK_API_KEY", llm_raw.get("api_key", "")),
            base_url=llm_raw.get("base_url", "https://api.deepseek.com"),
            model=llm_raw.get("model", "deepseek-reasoner"),
            model_fallback=llm_raw.get("model_fallback", "deepseek-chat"),
            temperature=llm_raw.get("temperature", 0.3),
            max_tokens=llm_raw.get("max_tokens", 1024),
        ),
        loops=loops,
        tuning=TuningConfig(
            max_change_ratio=tuning_raw.get("max_change_ratio", 0.2),
            min_change_threshold=tuning_raw.get("min_change_threshold", 0.01),
            history_window=tuning_raw.get("history_window", 10),
            data_sample_count=tuning_raw.get("data_sample_count", 50),
            convergence_patience=tuning_raw.get("convergence_patience", 3),
        ),
        online=OnlineConfig(
            tune_interval_s=online_raw.get("tune_interval_s", 10.0),
            data_buffer_size=online_raw.get("data_buffer_size", 200),
            auto_apply=online_raw.get("auto_apply", False),
        ),
    )


def save_config(config: AppConfig, path: Path | str | None = None) -> None:
    """Save current configuration to JSON file."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    raw: dict[str, Any] = {
        "serial": {
            "port": config.serial.port,
            "baudrate": config.serial.baudrate,
            "timeout": config.serial.timeout,
            "encoding": config.serial.encoding,
        },
        "llm": {
            "base_url": config.llm.base_url,
            "model": config.llm.model,
            "model_fallback": config.llm.model_fallback,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
        },
        "loops": {},
        "tuning": {
            "max_change_ratio": config.tuning.max_change_ratio,
            "min_change_threshold": config.tuning.min_change_threshold,
            "history_window": config.tuning.history_window,
            "data_sample_count": config.tuning.data_sample_count,
            "convergence_patience": config.tuning.convergence_patience,
        },
        "online": {
            "tune_interval_s": config.online.tune_interval_s,
            "data_buffer_size": config.online.data_buffer_size,
            "auto_apply": config.online.auto_apply,
        },
    }

    for loop_name, loop_cfg in config.loops.items():
        raw["loops"][loop_name] = {
            "name": loop_cfg.name,
            "pid": loop_cfg.pid.to_dict(),
            "limits": {
                "kp": [loop_cfg.limits.kp_min, loop_cfg.limits.kp_max],
                "ki": [loop_cfg.limits.ki_min, loop_cfg.limits.ki_max],
                "kd": [loop_cfg.limits.kd_min, loop_cfg.limits.kd_max],
            },
            "target_metrics": {
                "max_overshoot_pct": loop_cfg.target_metrics.max_overshoot_pct,
                "max_settling_time_s": loop_cfg.target_metrics.max_settling_time_s,
                "max_sse_pct": loop_cfg.target_metrics.max_sse_pct,
            },
            "description": loop_cfg.description,
        }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)

    logger.info("Config saved to %s", config_path)
