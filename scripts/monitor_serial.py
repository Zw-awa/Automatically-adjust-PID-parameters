"""Monitor serial port and display incoming data.

Standalone utility script for debugging serial communication.
Displays parsed messages and optionally saves raw data to file.

Usage:
  python scripts/monitor_serial.py --port COM3
  python scripts/monitor_serial.py --port COM3 --save data/raw/monitor.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import SerialConfig, load_config
from core.serial_manager import SerialManager, ParsedMessage


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor serial port")
    parser.add_argument("--port", "-p", help="Serial port (e.g. COM3)")
    parser.add_argument("--baud", "-b", type=int, help="Baud rate")
    parser.add_argument("--save", "-s", help="Save raw data to CSV file")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)

    serial_cfg = SerialConfig(
        port=args.port or config.serial.port,
        baudrate=args.baud or config.serial.baudrate,
        timeout=config.serial.timeout,
        encoding=config.serial.encoding,
    )

    save_file = None
    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_file = open(save_path, "w", encoding="utf-8")
        save_file.write("timestamp,target,actual,error,output\n")

    print(f"Monitoring {serial_cfg.port} @ {serial_cfg.baudrate} baud")
    print("Press Ctrl+C to stop\n")

    mgr = SerialManager(serial_cfg)
    count = 0

    try:
        mgr.open()

        while True:
            msg = mgr.read_line()
            if msg is None:
                continue

            count += 1

            if msg.msg_type == "DATA" and msg.data_sample:
                s = msg.data_sample
                print(
                    f"[{count:>5}] {msg.loop_name:>10} | "
                    f"t={s.target:>8.2f} a={s.actual:>8.2f} "
                    f"e={s.error:>8.2f} o={s.output:>8.2f}"
                )
                if save_file:
                    save_file.write(
                        f"{s.timestamp:.6f},{s.target:.4f},"
                        f"{s.actual:.4f},{s.error:.4f},{s.output:.4f}\n"
                    )
                    save_file.flush()
            elif msg.msg_type == "ACK":
                print(f"[{count:>5}] ACK {msg.loop_name}: {msg.payload}")
            elif msg.msg_type == "INFO":
                print(f"[{count:>5}] INFO: {msg.payload}")
            else:
                print(f"[{count:>5}] RAW: {msg.payload}")

    except KeyboardInterrupt:
        print(f"\n\nStopped. {count} messages received.")
    finally:
        mgr.close()
        if save_file:
            save_file.close()
            print(f"Data saved to {args.save}")


if __name__ == "__main__":
    main()
