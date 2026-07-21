"""Serial communication manager.

Handles UART communication with the MCU (microcontroller).
Supports sending PID parameters and receiving sensor data
using a defined text protocol.

## Serial Protocol

### MCU -> PC (data report):
    DATA:<loop>:<timestamp>,<target>,<actual>,<error>,<output>\n
    Example: DATA:speed:12345,100.0,95.3,-4.7,85.2\n

### PC -> MCU (parameter update):
    PID:<request_id>:<loop>:<Kp>,<Ki>,<Kd>\n

### MCU -> PC (acknowledgment/rejection):
    ACK:<request_id>:<loop>:<applied_Kp>,<applied_Ki>,<applied_Kd>\n
    NACK:<request_id>:<loop>:<reason>\n

### MCU -> PC (status/info):
    INFO:<message>\n
    Example: INFO:System started, PID initialized\n
"""

from __future__ import annotations

import logging
import math
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial

from core.analyzer import DataSample
from core.config import PIDParams, SerialConfig

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def new_request_id() -> str:
    return secrets.token_hex(6)


def format_pid_command(
    loop_name: str,
    params: PIDParams,
    *,
    request_id: str | None = None,
) -> str:
    """Format a validated protocol-v2 PID command without its line ending."""
    request_id = request_id or new_request_id()
    _validate_token("request_id", request_id)
    _validate_token("loop_name", loop_name)
    if not all(math.isfinite(value) for value in (params.kp, params.ki, params.kd)):
        raise ValueError("PID parameters must be finite")
    return (
        f"PID:{request_id}:{loop_name}:"
        f"{params.kp:.6f},{params.ki:.6f},{params.kd:.6f}"
    )


@dataclass(frozen=True)
class ParsedMessage:
    """A parsed serial message."""

    msg_type: str      # "DATA", "ACK", "INFO", "UNKNOWN"
    loop_name: str     # e.g., "speed", "steering"
    payload: str       # Raw payload string
    data_sample: DataSample | None = None
    ack_params: PIDParams | None = None
    request_id: str | None = None
    error_code: str | None = None


def parse_line(line: str) -> ParsedMessage:
    """Parse a single line from serial input.

    Args:
        line: Raw line string (already stripped of newline).

    Returns:
        ParsedMessage with parsed contents.
    """
    line = line.strip()
    if not line:
        return ParsedMessage(msg_type="UNKNOWN", loop_name="", payload="")

    parts = line.split(":")

    if len(parts) < 2:
        return ParsedMessage(msg_type="INFO", loop_name="", payload=line)

    msg_type = parts[0].upper()

    if msg_type == "DATA" and len(parts) == 3:
        loop_name = parts[1]
        return _parse_data_message(loop_name, parts[2])

    if msg_type == "ACK" and len(parts) == 4:
        return _parse_ack_message(parts[2], parts[3], request_id=parts[1])

    if msg_type == "NACK" and len(parts) >= 4:
        return ParsedMessage(
            msg_type="NACK",
            loop_name=parts[2],
            payload=":".join(parts[3:]),
            request_id=parts[1],
            error_code=parts[3],
        )

    # Receive-only compatibility for old firmware.
    if msg_type == "ACK" and len(parts) == 3:
        loop_name = parts[1]
        return _parse_ack_message(loop_name, parts[2])

    if msg_type == "INFO":
        payload = ":".join(parts[1:])
        return ParsedMessage(msg_type="INFO", loop_name="", payload=payload)

    return ParsedMessage(msg_type="UNKNOWN", loop_name="", payload=line)


def _parse_data_message(loop_name: str, payload: str) -> ParsedMessage:
    """Parse DATA message payload: timestamp,target,actual,error,output"""
    values = payload.split(",")
    try:
        if len(values) >= 5:
            sample = DataSample(
                timestamp=float(values[0].strip()),
                target=float(values[1].strip()),
                actual=float(values[2].strip()),
                error=float(values[3].strip()),
                output=float(values[4].strip()),
            )
        elif len(values) >= 3:
            ts = float(values[0].strip())
            target = float(values[1].strip())
            actual = float(values[2].strip())
            sample = DataSample(
                timestamp=ts,
                target=target,
                actual=actual,
                error=target - actual,
                output=0.0,
            )
        else:
            return ParsedMessage(
                msg_type="DATA", loop_name=loop_name, payload=payload
            )

        return ParsedMessage(
            msg_type="DATA",
            loop_name=loop_name,
            payload=payload,
            data_sample=sample,
        )
    except ValueError as e:
        logger.warning("Failed to parse DATA payload: %s (%s)", payload, e)
        return ParsedMessage(msg_type="DATA", loop_name=loop_name, payload=payload)


def _parse_ack_message(
    loop_name: str,
    payload: str,
    *,
    request_id: str | None = None,
) -> ParsedMessage:
    """Parse ACK message payload: Kp,Ki,Kd"""
    values = payload.split(",")
    try:
        if len(values) >= 3:
            params = PIDParams(
                kp=float(values[0].strip()),
                ki=float(values[1].strip()),
                kd=float(values[2].strip()),
            )
            if not all(math.isfinite(value) for value in (params.kp, params.ki, params.kd)):
                raise ValueError("ACK contains non-finite parameters")
            return ParsedMessage(
                msg_type="ACK",
                loop_name=loop_name,
                payload=payload,
                ack_params=params,
                request_id=request_id,
            )
    except ValueError as e:
        logger.warning("Failed to parse ACK payload: %s (%s)", payload, e)

    return ParsedMessage(
        msg_type="ACK",
        loop_name=loop_name,
        payload=payload,
        request_id=request_id,
    )


class SerialManager:
    """Manages serial port connection and communication.

    Thread-safe: uses a lock for write operations and runs
    a background reader thread for incoming data.
    ACK messages are routed through a queue to avoid race conditions.
    """

    def __init__(self, config: SerialConfig) -> None:
        self._config = config
        self._port: serial.Serial | None = None
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_data: Callable[[ParsedMessage], None] | None = None
        self._ack_queues: dict[str, queue.Queue[ParsedMessage]] = {}

    @property
    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def open(self) -> None:
        """Open the serial port."""
        if self.is_open:
            logger.warning("Serial port already open")
            return

        self._port = serial.Serial(
            port=self._config.port,
            baudrate=self._config.baudrate,
            timeout=self._config.timeout,
        )
        logger.info(
            "Serial port opened: %s @ %d baud",
            self._config.port,
            self._config.baudrate,
        )

    def close(self) -> None:
        """Close the serial port and stop reader thread."""
        self.stop_reader()
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
                logger.info("Serial port closed")
            self._port = None

    def send_pid(
        self,
        loop_name: str,
        params: PIDParams,
        *,
        request_id: str | None = None,
    ) -> str:
        """Send PID parameters and return the correlation request ID."""
        request_id = request_id or new_request_id()
        command = format_pid_command(loop_name, params, request_id=request_id)
        self._write(command + "\n")
        logger.info(
            "Sent PID to %s: Kp=%.6f Ki=%.6f Kd=%.6f",
            loop_name, params.kp, params.ki, params.kd,
        )
        return request_id

    def _write(self, data: str) -> None:
        """Thread-safe write to serial port."""
        with self._lock:
            if not self.is_open:
                raise RuntimeError("Serial port is not open")
            assert self._port is not None
            self._port.write(data.encode(self._config.encoding))
            self._port.flush()

    def read_line(self) -> ParsedMessage | None:
        """Read and parse a single line from serial port.

        Returns None if no data available (timeout).
        Note: Do NOT call this while the background reader is running.
        """
        if not self.is_open:
            raise RuntimeError("Serial port is not open")
        assert self._port is not None

        try:
            raw = self._port.readline()
            if not raw:
                return None

            line = raw.decode(self._config.encoding, errors="replace").strip()
            if not line:
                return None

            return parse_line(line)
        except serial.SerialException as e:
            logger.error("Serial read error: %s", e)
            return None

    def start_reader(
        self,
        callback: Callable[[ParsedMessage], None],
    ) -> None:
        """Start background thread that continuously reads serial data.

        Args:
            callback: Called for each parsed message (on reader thread).
        """
        if not self._stop_event.is_set() and self._reader_thread is not None:
            logger.warning("Reader already running")
            return

        self._on_data = callback
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="serial-reader",
            daemon=True,
        )
        self._reader_thread.start()
        logger.info("Serial reader thread started")

    def stop_reader(self) -> None:
        """Stop the background reader thread."""
        self._stop_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)
            logger.info("Serial reader thread stopped")
        self._reader_thread = None

    def prepare_ack_queue(self, request_id: str) -> queue.Queue[ParsedMessage]:
        """Register an ACK queue before sending a command.

        Registering first avoids a race where the MCU responds so quickly
        that the reader thread consumes the ACK before `wait_for_ack()`
        has created its queue.
        """
        _validate_token("request_id", request_id)
        q: queue.Queue[ParsedMessage] = queue.Queue()
        self._ack_queues[request_id] = q
        return q

    def _reader_loop(self) -> None:
        """Background loop that reads serial data."""
        while not self._stop_event.is_set():
            try:
                msg = self.read_line()
                if msg is None:
                    continue

                if (
                    msg.msg_type in ("ACK", "NACK")
                    and msg.request_id in self._ack_queues
                ):
                    self._ack_queues[msg.request_id].put(msg)

                # Always forward to data callback
                if self._on_data:
                    self._on_data(msg)
            except Exception as e:
                logger.error("Reader loop error: %s", e)
                time.sleep(0.1)

    def wait_for_ack(
        self,
        request_id: str,
        loop_name: str,
        expected_params: PIDParams,
        timeout: float = 5.0,
        ack_queue: queue.Queue[ParsedMessage] | None = None,
    ) -> PIDParams | None:
        """Wait for an ACK message for a specific loop.

        Safe to call while the background reader is running — ACK messages
        are routed through an internal queue, avoiding readline() races.

        Args:
            loop_name: Expected loop name in ACK.
            timeout: Maximum wait time in seconds.

        Returns:
            Acknowledged PID params, or None if timeout.
        """
        q = ack_queue or self.prepare_ack_queue(request_id)
        try:
            message = q.get(timeout=timeout)
            if message.msg_type == "NACK":
                raise RuntimeError(
                    f"Device rejected PID update for {loop_name}: {message.payload}"
                )
            params = message.ack_params
            if message.loop_name != loop_name or params is None:
                raise RuntimeError("Received malformed or mismatched PID acknowledgment")
            tolerance = 1e-5
            if any(
                abs(actual - expected) > tolerance
                for actual, expected in (
                    (params.kp, expected_params.kp),
                    (params.ki, expected_params.ki),
                    (params.kd, expected_params.kd),
                )
            ):
                raise RuntimeError("Acknowledged PID values do not match requested values")
            logger.info("ACK received for request %s (%s)", request_id, loop_name)
            return params
        except queue.Empty:
            logger.warning("ACK timeout for %s after %.1fs", loop_name, timeout)
            return None
        finally:
            if self._ack_queues.get(request_id) is q:
                self._ack_queues.pop(request_id, None)


def _validate_token(name: str, value: str) -> None:
    if not _TOKEN_RE.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")
