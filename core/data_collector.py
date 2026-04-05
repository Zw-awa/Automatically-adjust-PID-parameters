"""Data collector module.

Manages real-time data collection from serial port, maintains
an in-memory ring buffer, and saves data to CSV files.
"""

from __future__ import annotations

import csv
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from core.analyzer import DataSample
from core.serial_manager import ParsedMessage

logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

CSV_HEADER = ["timestamp", "target", "actual", "error", "output"]


class DataCollector:
    """Collects and buffers sensor data from serial port.

    Thread-safe ring buffer that can be used as a callback
    for SerialManager.start_reader().
    """

    def __init__(
        self,
        loop_name: str,
        buffer_size: int = 200,
    ) -> None:
        self._loop_name = loop_name
        self._buffer: deque[DataSample] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._total_received = 0
        self._csv_writer: _CsvRecorder | None = None

    @property
    def loop_name(self) -> str:
        return self._loop_name

    @property
    def buffer_size(self) -> int:
        return self._buffer.maxlen or 0

    @property
    def count(self) -> int:
        """Number of samples currently in buffer."""
        with self._lock:
            return len(self._buffer)

    @property
    def total_received(self) -> int:
        """Total number of samples received since start."""
        return self._total_received

    def on_serial_message(self, msg: ParsedMessage) -> None:
        """Callback for SerialManager reader thread.

        Filters messages by loop name and stores DATA samples.
        """
        if msg.msg_type != "DATA":
            return
        if msg.loop_name != self._loop_name:
            return
        if msg.data_sample is None:
            return

        self.add_sample(msg.data_sample)

    def add_sample(self, sample: DataSample) -> None:
        """Add a data sample to the buffer."""
        with self._lock:
            self._buffer.append(sample)
            self._total_received += 1

        # Also write to CSV if recording
        if self._csv_writer:
            self._csv_writer.write_sample(sample)

    def get_recent(self, n: int | None = None) -> list[DataSample]:
        """Get the most recent N samples from the buffer.

        Args:
            n: Number of samples. None = all buffered samples.

        Returns:
            List of DataSample (oldest first).
        """
        with self._lock:
            if n is None:
                return list(self._buffer)
            return list(self._buffer)[-n:]

    def get_all(self) -> list[DataSample]:
        """Get all buffered samples."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._buffer.clear()

    def start_recording(self, filepath: Path | str | None = None) -> Path:
        """Start recording all incoming data to a CSV file.

        Args:
            filepath: Target CSV file. Auto-generated if None.

        Returns:
            Path of the recording file.
        """
        if filepath is None:
            RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = RAW_DATA_DIR / f"{self._loop_name}_{timestamp}.csv"
        else:
            filepath = Path(filepath)

        filepath.parent.mkdir(parents=True, exist_ok=True)

        self._csv_writer = _CsvRecorder(filepath)
        self._csv_writer.start()

        logger.info("Started recording to %s", filepath)
        return filepath

    def stop_recording(self) -> Path | None:
        """Stop recording and close the CSV file.

        Returns:
            Path of the recorded file, or None if not recording.
        """
        if self._csv_writer is None:
            return None

        path = self._csv_writer.filepath
        self._csv_writer.stop()
        self._csv_writer = None

        logger.info("Stopped recording: %s", path)
        return path


class _CsvRecorder:
    """Internal helper that writes DataSamples to a CSV file."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self._file = None
        self._writer = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._file = open(self.filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_HEADER)

    def write_sample(self, sample: DataSample) -> None:
        with self._lock:
            if self._writer is None:
                return
            self._writer.writerow([
                f"{sample.timestamp:.6f}",
                f"{sample.target:.4f}",
                f"{sample.actual:.4f}",
                f"{sample.error:.4f}",
                f"{sample.output:.4f}",
            ])
            if self._file:
                self._file.flush()

    def stop(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
            self._file = None
            self._writer = None


def load_csv_samples(filepath: str | Path) -> list[DataSample]:
    """Load DataSamples from a CSV file.

    Convenience wrapper around analyzer.parse_csv_data.
    """
    from core.analyzer import parse_csv_data
    return parse_csv_data(str(filepath))
