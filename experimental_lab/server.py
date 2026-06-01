"""Local HTTP and WebSocket server for the experimental lab."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import mimetypes
import os
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.config import AppConfig, PIDParams, load_config
from experimental_lab import DEFAULT_DB_PATH, DEFAULT_HOST, DEFAULT_PORT
from experimental_lab.models import MetricSnapshot
from experimental_lab.runner import LabRunnerManager, build_default_settings
from experimental_lab.scoring import score_from_payload
from experimental_lab.storage import LabStorage

logger = logging.getLogger(__name__)

SITE_ROOT = Path(__file__).parent.parent / "site" / "lab"


class WebSocketClient:
    """Minimal WebSocket sender used for server-to-client events."""

    def __init__(self, request_handler: BaseHTTPRequestHandler) -> None:
        self._handler = request_handler
        self._lock = threading.Lock()

    def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with self._lock:
            _send_ws_frame(self._handler.wfile, data)

    def close(self) -> None:
        try:
            with self._lock:
                self._handler.connection.shutdown(2)
                self._handler.connection.close()
        except OSError:
            pass


class WebSocketHub:
    """Broadcast JSON events to all attached clients."""

    def __init__(self) -> None:
        self._clients: set[WebSocketClient] = set()
        self._lock = threading.Lock()

    def register(self, client: WebSocketClient) -> None:
        with self._lock:
            self._clients.add(client)

    def unregister(self, client: WebSocketClient) -> None:
        with self._lock:
            self._clients.discard(client)

    def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocketClient] = []
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.send_json(payload)
            except OSError:
                stale.append(client)
        if stale:
            with self._lock:
                for client in stale:
                    self._clients.discard(client)


@dataclass
class LabServerState:
    """Shared application state for HTTP handlers and workers."""

    config: AppConfig
    storage: LabStorage
    hub: WebSocketHub
    runner: LabRunnerManager
    static_root: Path

    def publish(self, session_id: int, event_type: str, payload: dict[str, Any]) -> None:
        event = self.storage.append_event(session_id, event_type, payload)
        self.hub.broadcast(
            {
                "type": event_type,
                "session_id": session_id,
                "payload": payload,
                "created_at": event["created_at"],
            }
        )


class LabHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying shared lab state."""

    def __init__(self, server_address: tuple[str, int], state: LabServerState) -> None:
        self.state = state
        super().__init__(server_address, LabRequestHandler)


class LabRequestHandler(BaseHTTPRequestHandler):
    """REST and static handler for the lab UI."""

    server_version = "PIDLab/0.1"

    @property
    def state(self) -> LabServerState:
        return self.server.state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "db_path": str(self.state.storage.db_path)})
            return
        if parsed.path == "/api/config":
            self._send_json(self._config_payload())
            return
        if parsed.path == "/api/files":
            self._send_json({"files": self._list_csv_files(parse_qs(parsed.query).get("kind", ["csv"])[0])})
            return
        if parsed.path == "/api/sessions":
            sessions = [session.to_dict() for session in self.state.storage.list_sessions()]
            self._send_json({"sessions": sessions})
            return
        if parsed.path.startswith("/api/sessions/"):
            self._handle_session_get(parsed.path)
            return
        if parsed.path == "/ws":
            self._upgrade_websocket()
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sessions":
            payload = self._read_json_body()
            self._create_session(payload)
            return
        if parsed.path.startswith("/api/sessions/"):
            self._handle_session_post(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/sessions/"):
            self._patch_session(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/records/"):
            self._delete_record(parsed.path)
            return
        if parsed.path.startswith("/api/sessions/"):
            self._delete_session_or_records(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _config_payload(self) -> dict[str, Any]:
        loops: list[dict[str, Any]] = []
        for key, loop in self.state.config.loops.items():
            loops.append(
                {
                    "key": key,
                    "name": loop.name,
                    "description": loop.description,
                    "pid": loop.pid.to_dict(),
                    "target_metrics": {
                        "max_overshoot_pct": loop.target_metrics.max_overshoot_pct,
                        "max_settling_time_s": loop.target_metrics.max_settling_time_s,
                        "max_sse_pct": loop.target_metrics.max_sse_pct,
                    },
                    "limits": {
                        "kp": [loop.limits.kp_min, loop.limits.kp_max],
                        "ki": [loop.limits.ki_min, loop.limits.ki_max],
                        "kd": [loop.limits.kd_min, loop.limits.kd_max],
                    },
                }
            )
        return {
            "loops": loops,
            "strategies": ["llm", "bo", "hybrid"],
            "modes": ["simulate", "offline"],
        }

    def _handle_session_get(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown session endpoint")
            return
        session_id = int(parts[2])
        if len(parts) == 3:
            self._send_json(self._session_snapshot(session_id))
            return
        if len(parts) == 4 and parts[3] == "records":
            records = [record.to_dict() for record in self.state.storage.list_records(session_id)]
            self._send_json({"records": records})
            return
        if len(parts) == 4 and parts[3] == "events":
            self._send_json({"events": self.state.storage.list_events(session_id)})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown session endpoint")

    def _handle_session_post(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 4:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown session endpoint")
            return
        session_id = int(parts[2])
        action = parts[3]
        payload = self._read_json_body(allow_empty=True)
        if action == "records":
            self._add_manual_record(session_id, payload)
            return
        if action == "run":
            if len(parts) != 5:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown run action")
                return
            run_action = parts[4]
            self._run_action(session_id, run_action)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown session endpoint")

    def _create_session(self, payload: dict[str, Any]) -> None:
        mode = str(payload.get("mode", "simulate"))
        loop_name = str(payload.get("loop_name", "speed"))
        strategy = str(payload.get("strategy", "hybrid"))
        name = str(payload.get("name") or f"{loop_name}-{mode}")
        notes = str(payload.get("notes", ""))
        overrides = payload.get("settings", {})
        if not isinstance(overrides, dict):
            overrides = {}
        settings = build_default_settings(
            self.state.config,
            loop_name=loop_name,
            mode=mode,
            strategy=strategy,
            overrides=overrides,
        )
        session = self.state.storage.create_session(
            name=name,
            loop_name=loop_name,
            mode=mode,
            strategy=strategy,
            settings=settings,
            notes=notes,
        )
        self.state.publish(session.id, "session.created", {"session": session.to_dict()})
        self._send_json({"session": session.to_dict()}, status=HTTPStatus.CREATED)

    def _patch_session(self, path: str) -> None:
        session_id = int(path.rstrip("/").split("/")[-1])
        payload = self._read_json_body()
        session = self.state.storage.get_session(session_id)
        settings = session.settings
        if "settings" in payload and isinstance(payload["settings"], dict):
            settings = dict(session.settings)
            settings.update(payload["settings"])
        updated = self.state.storage.update_session(
            session_id,
            name=payload.get("name"),
            strategy=payload.get("strategy"),
            notes=payload.get("notes"),
            settings=settings,
        )
        self.state.publish(session_id, "session.updated", {"session": updated.to_dict()})
        self._send_json({"session": updated.to_dict()})

    def _delete_session_or_records(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3:
            session_id = int(parts[2])
            self.state.storage.delete_session(session_id)
            self.state.hub.broadcast(
                {
                    "type": "session.deleted",
                    "session_id": session_id,
                    "payload": {"session_id": session_id},
                }
            )
            self._send_json({"deleted": True, "session_id": session_id})
            return
        if len(parts) == 4 and parts[3] == "records":
            session_id = int(parts[2])
            self.state.storage.clear_records(session_id)
            session = self.state.storage.get_session(session_id)
            self.state.publish(session_id, "records.cleared", {"session": session.to_dict()})
            self._send_json({"cleared": True, "session": session.to_dict()})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown session endpoint")

    def _delete_record(self, path: str) -> None:
        record_id = int(path.rstrip("/").split("/")[-1])
        session_id = self.state.storage.delete_record(record_id)
        if session_id is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown record")
            return
        self.state.publish(
            session_id,
            "record.deleted",
            {"session_id": session_id, "record_id": record_id},
        )
        self._send_json({"deleted": True, "record_id": record_id, "session_id": session_id})

    def _add_manual_record(self, session_id: int, payload: dict[str, Any]) -> None:
        session = self.state.storage.get_session(session_id)
        settings = dict(session.settings)
        pid_payload = payload.get("pid") or {}
        pid = PIDParams(
            kp=float(pid_payload.get("kp", session.current_pid.kp)),
            ki=float(pid_payload.get("ki", session.current_pid.ki)),
            kd=float(pid_payload.get("kd", session.current_pid.kd)),
        )
        prev_payload = payload.get("prev_pid") or session.current_pid.to_dict()
        prev_pid = PIDParams(
            kp=float(prev_payload.get("kp", session.current_pid.kp)),
            ki=float(prev_payload.get("ki", session.current_pid.ki)),
            kd=float(prev_payload.get("kd", session.current_pid.kd)),
        )
        metrics_payload = payload.get("metrics") or {}
        score = score_from_payload(
            metrics_payload,
            self.state.config.get_loop(session.loop_name).target_metrics,
            weights=settings.get("score_weights"),
        )
        metrics = MetricSnapshot(
            overshoot_pct=float(metrics_payload.get("overshoot_pct", 0.0)),
            settling_time_s=float(metrics_payload.get("settling_time_s", 0.0)),
            steady_state_error_pct=float(metrics_payload.get("steady_state_error_pct", 0.0)),
            oscillation_count=int(metrics_payload.get("oscillation_count", 0)),
            is_diverging=bool(metrics_payload.get("is_diverging", False)),
            is_saturated=bool(metrics_payload.get("is_saturated", False)),
        )
        record = self.state.storage.add_record(
            session_id=session_id,
            iteration_index=self.state.storage.next_iteration_index(session_id),
            source="manual",
            applied=True,
            strategy_name=session.strategy,
            model_used="manual-entry",
            prev_pid=prev_pid,
            pid=pid,
            metrics=metrics,
            score=score.score,
            is_good=score.is_good,
            quality_label=score.quality_label,
            reason=str(payload.get("reason", "Manual observation")),
            confidence=float(payload.get("confidence", 0.5)),
            expected_improvement=str(payload.get("expected_improvement", "User-supplied observation.")),
            raw_data_path=payload.get("raw_data_path"),
            note=str(payload.get("note", "")),
            strategy_metadata={"score_breakdown": score.breakdown, "source": "manual"},
        )
        settings["current_pid"] = pid.to_dict()
        updated = self.state.storage.update_session(session_id, settings=settings)
        self.state.publish(
            session_id,
            "record.added",
            {"record": record.to_dict(), "session": updated.to_dict()},
        )
        self._send_json({"record": record.to_dict(), "session": updated.to_dict()}, status=HTTPStatus.CREATED)

    def _run_action(self, session_id: int, action: str) -> None:
        if action == "start":
            self.state.runner.start(session_id)
        elif action == "pause":
            self.state.runner.pause(session_id)
        elif action == "resume":
            self.state.runner.resume(session_id)
        elif action == "stop":
            self.state.runner.stop(session_id)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown run action")
            return
        session = self.state.storage.get_session(session_id)
        self._send_json({"ok": True, "session": session.to_dict()})

    def _session_snapshot(self, session_id: int) -> dict[str, Any]:
        session = self.state.storage.get_session(session_id)
        records = [record.to_dict() for record in self.state.storage.list_records(session_id)]
        events = self.state.storage.list_events(session_id)
        return {"session": session.to_dict(), "records": records, "events": events}

    def _list_csv_files(self, kind: str) -> list[str]:
        if kind != "csv":
            return []
        root = Path("data") / "raw"
        if not root.exists():
            return []
        files = sorted(path.as_posix() for path in root.rglob("*.csv"))
        return files

    def _serve_static(self, path: str) -> None:
        clean_path = path
        if clean_path in ("/", ""):
            clean_path = "/lab/"
        if clean_path == "/lab":
            clean_path = "/lab/"
        if clean_path == "/lab/":
            clean_path = "/lab/index.html"
        if not clean_path.startswith("/lab/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        relative = clean_path[len("/lab/") :]
        target = (self.state.static_root / relative).resolve()
        if not str(target).startswith(str(self.state.static_root.resolve())) or not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        with open(target, "rb") as handle:
            data = handle.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _upgrade_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing WebSocket key")
            return
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        client = WebSocketClient(self)
        self.state.hub.register(client)
        try:
            while True:
                opcode = _read_ws_frame(self.connection)
                if opcode in (None, 8):
                    break
        except OSError:
            pass
        finally:
            self.state.hub.unregister(client)

    def _read_json_body(self, *, allow_empty: bool = False) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            if allow_empty:
                return {}
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


def _send_ws_frame(buffer: Any, payload: bytes) -> None:
    length = len(payload)
    header = bytearray([0x81])
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    buffer.write(bytes(header) + payload)
    buffer.flush()


def _read_exact(connection: Any, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _read_ws_frame(connection: Any) -> int | None:
    header = _read_exact(connection, 2)
    if not header:
        return None
    first, second = header
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        extended = _read_exact(connection, 2)
        if extended is None:
            return None
        length = int.from_bytes(extended, "big")
    elif length == 127:
        extended = _read_exact(connection, 8)
        if extended is None:
            return None
        length = int.from_bytes(extended, "big")
    masked = bool(second & 0x80)
    mask = _read_exact(connection, 4) if masked else None
    payload = _read_exact(connection, length)
    if payload is None:
        return None
    if masked and mask is not None:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 9:
        # Browser ping: answer with pong.
        response = bytearray([0x8A])
        response.append(len(payload))
        connection.sendall(bytes(response) + payload)
    return opcode


class LabServer:
    """Convenience wrapper around the HTTP server lifecycle."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        config: AppConfig,
        db_path: str,
    ) -> None:
        storage = LabStorage(db_path)
        hub = WebSocketHub()
        state = LabServerState(
            config=config,
            storage=storage,
            hub=hub,
            runner=LabRunnerManager(storage, config, publish=lambda s, t, p: state.publish(s, t, p)),
            static_root=SITE_ROOT,
        )
        self._server = LabHTTPServer((host, port), state)
        self.state = state
        self.host = host
        self.port = self._server.server_address[1]

    def serve_forever(self) -> None:
        logger.info("PID experimental lab listening on http://%s:%s/lab/", self.host, self.port)
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.state.storage.close()

    def start_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


def run_lab_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config_path: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
    open_browser: bool = True,
) -> None:
    """CLI entrypoint for the experimental lab server."""
    config = load_config(config_path)
    server = LabServer(host=host, port=port, config=config, db_path=db_path)
    try:
        if open_browser:
            webbrowser.open(f"http://{host}:{server.port}/lab/")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down lab server")
    finally:
        server.shutdown()


def build_lab_parser() -> argparse.ArgumentParser:
    """Construct a parser that can be embedded in main.py or scripts."""
    parser = argparse.ArgumentParser(description="Run the PID experimental lab")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind the local lab server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind the local lab server")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the lab in the browser")
    return parser


def main() -> None:
    parser = build_lab_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    run_lab_server(
        host=args.host,
        port=args.port,
        config_path=args.config,
        db_path=args.db,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
