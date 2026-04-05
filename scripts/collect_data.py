"""Collect serial data for a specified duration and save to CSV.

Usage:
  python scripts/collect_data.py --port COM3 --loop speed --duration 30
  python scripts/collect_data.py --port COM3 --loop speed --count 500
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import SerialConfig, load_config
from core.data_collector import DataCollector
from core.serial_manager import SerialManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect serial data to CSV")
    parser.add_argument("--port", "-p", help="Serial port")
    parser.add_argument("--loop", "-l", required=True, help="Loop name to collect")
    parser.add_argument("--duration", "-d", type=float, help="Collection duration (seconds)")
    parser.add_argument("--count", "-c", type=int, help="Number of samples to collect")
    parser.add_argument("--output", "-o", help="Output CSV file path")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    serial_cfg = SerialConfig(
        port=args.port or config.serial.port,
        baudrate=config.serial.baudrate,
        timeout=config.serial.timeout,
        encoding=config.serial.encoding,
    )

    collector = DataCollector(
        loop_name=args.loop,
        buffer_size=max(args.count or 1000, 1000),
    )

    output_path = collector.start_recording(args.output)

    print(f"Collecting '{args.loop}' data from {serial_cfg.port}")
    print(f"Saving to: {output_path}")

    if args.duration:
        print(f"Duration: {args.duration}s")
    elif args.count:
        print(f"Target samples: {args.count}")
    else:
        print("Press Ctrl+C to stop")

    mgr = SerialManager(serial_cfg)

    try:
        mgr.open()
        mgr.start_reader(collector.on_serial_message)

        start_time = time.time()

        while True:
            time.sleep(0.5)
            elapsed = time.time() - start_time

            sys.stdout.write(
                f"\r  {collector.total_received} samples collected "
                f"({elapsed:.0f}s elapsed)  "
            )
            sys.stdout.flush()

            if args.duration and elapsed >= args.duration:
                break
            if args.count and collector.total_received >= args.count:
                break

    except KeyboardInterrupt:
        pass
    finally:
        mgr.close()
        collector.stop_recording()

    print(f"\n\nDone. {collector.total_received} samples saved to {output_path}")


if __name__ == "__main__":
    main()
