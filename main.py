"""Automatically-adjust-PID-parameters - Main Entry Point.

Usage:
  python main.py offline --file data.csv --loop speed
  python main.py online --port COM3 --loop speed --interval 10
  python main.py simulate --loop speed --iterations 5
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.config import load_config
from core.workflows import run_offline, run_online, run_simulate
from experimental_lab.server import run_lab_server


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        description="Automatically-adjust-PID-parameters - LLM-based PID parameter tuning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Offline mode: analyze a saved CSV data file
  python main.py offline --file data/raw/speed_data.csv --loop speed

  # Online mode: real-time tuning via serial
  # COM3 is only the default example. Change it to your actual serial port.
  python main.py online --port COM3 --loop speed --interval 10

  # Simulation mode: test without hardware
  python main.py simulate --loop speed --iterations 5

Serial Protocol (MCU must implement):
  MCU -> PC:  DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>
  PC -> MCU:  PID:<loop>:<Kp>,<Ki>,<Kd>
  MCU -> PC:  ACK:<loop>:<Kp>,<Ki>,<Kd>
""",
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (default: ./config.json, fallback: ./config.example.json)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="mode", help="Operating mode")

    offline = subparsers.add_parser("offline", help="Offline tuning from CSV file")
    offline.add_argument("--file", "-f", required=True, help="CSV data file path")
    offline.add_argument("--loop", "-l", required=True, help="Control loop name")
    offline.add_argument("--history", help="Previous history JSON file")

    online = subparsers.add_parser("online", help="Online tuning via serial")
    online.add_argument("--loop", "-l", required=True, help="Control loop name")
    online.add_argument("--port", "-p", help="Serial port (overrides config)")
    online.add_argument("--interval", "-i", type=float, help="Tune interval (seconds)")
    online.add_argument("--max-iter", type=int, help="Max tuning iterations")

    simulate = subparsers.add_parser("simulate", help="Simulation mode (no hardware)")
    simulate.add_argument("--loop", "-l", required=True, help="Control loop name")
    simulate.add_argument("--iterations", "-n", type=int, default=5, help="Number of iterations")

    lab = subparsers.add_parser("lab", help="Launch the experimental tuning lab")
    lab.add_argument("--host", default="127.0.0.1", help="Local host for the lab server")
    lab.add_argument("--port", type=int, default=8765, help="Local port for the lab server")
    lab.add_argument("--db", default="data/lab/experimental_lab.sqlite3", help="SQLite database path for the lab")
    lab.add_argument("--no-browser", action="store_true", help="Do not auto-open the lab in the browser")

    return parser


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.mode:
        parser.print_help()
        sys.exit(0)

    config = load_config(args.config)

    if args.mode == "offline":
        run_offline(
            config=config,
            loop_name=args.loop,
            data_file=args.file,
            history_file=getattr(args, "history", None),
            config_path=args.config,
        )
    elif args.mode == "online":
        run_online(
            config=config,
            loop_name=args.loop,
            port=args.port,
            interval=args.interval,
            max_iterations=getattr(args, "max_iter", None),
            config_path=args.config,
        )
    elif args.mode == "simulate":
        run_simulate(
            config=config,
            loop_name=args.loop,
            iterations=args.iterations,
        )
    elif args.mode == "lab":
        run_lab_server(
            host=args.host,
            port=args.port,
            config_path=args.config,
            db_path=args.db,
            open_browser=not args.no_browser,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
