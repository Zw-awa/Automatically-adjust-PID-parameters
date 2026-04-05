"""Online tuning shortcut script.

Convenience wrapper around main.py online mode.

Usage:
  python scripts/online_tuner.py --port COM3 --loop speed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import load_config
from main import run_online


def main() -> None:
    parser = argparse.ArgumentParser(description="Online PID tuner")
    parser.add_argument("--port", "-p", help="Serial port")
    parser.add_argument("--loop", "-l", required=True, help="Loop name")
    parser.add_argument("--interval", "-i", type=float, default=10, help="Tune interval (s)")
    parser.add_argument("--auto", action="store_true", help="Auto-apply params")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.auto:
        # Override auto_apply
        from core.config import OnlineConfig
        config.online = OnlineConfig(
            tune_interval_s=config.online.tune_interval_s,
            data_buffer_size=config.online.data_buffer_size,
            auto_apply=True,
        )

    run_online(
        config=config,
        loop_name=args.loop,
        port=args.port,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
