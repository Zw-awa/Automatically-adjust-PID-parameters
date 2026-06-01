"""SQLite persistence for the experimental lab."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import PIDParams
from experimental_lab import DEFAULT_DB_PATH
from experimental_lab.models import MetricSnapshot, SessionRecord, SessionSummary


def utc_now() -> str:
    """Generate a stable UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class LabStorage:
    """Thread-safe SQLite access for lab state."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self.reset_running_sessions()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    loop_name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_settings (
                    session_id INTEGER PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    iteration_index INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    applied INTEGER NOT NULL,
                    strategy_name TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    prev_kp REAL NOT NULL,
                    prev_ki REAL NOT NULL,
                    prev_kd REAL NOT NULL,
                    kp REAL NOT NULL,
                    ki REAL NOT NULL,
                    kd REAL NOT NULL,
                    overshoot_pct REAL NOT NULL,
                    settling_time_s REAL NOT NULL,
                    steady_state_error_pct REAL NOT NULL,
                    oscillation_count INTEGER NOT NULL,
                    is_diverging INTEGER NOT NULL,
                    is_saturated INTEGER NOT NULL,
                    rise_time_s REAL,
                    peak_error REAL,
                    mean_abs_error REAL,
                    rms_error REAL,
                    data_points INTEGER,
                    score REAL,
                    is_good INTEGER,
                    quality_label TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    expected_improvement TEXT NOT NULL DEFAULT '',
                    raw_data_path TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    strategy_metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_records_session ON records(session_id, iteration_index);
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);
                """
            )

    def reset_running_sessions(self) -> None:
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET status = 'idle', updated_at = ? WHERE status IN ('running', 'paused')",
                (now,),
            )

    def create_session(
        self,
        *,
        name: str,
        loop_name: str,
        mode: str,
        strategy: str,
        settings: dict[str, Any],
        notes: str = "",
    ) -> SessionSummary:
        now = utc_now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO sessions(name, loop_name, mode, strategy, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'idle', ?, ?, ?)
                """,
                (name, loop_name, mode, strategy, notes, now, now),
            )
            session_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO session_settings(session_id, settings_json) VALUES (?, ?)",
                (session_id, json.dumps(settings, ensure_ascii=False)),
            )
        return self.get_session(session_id)

    def list_sessions(self) -> list[SessionSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self.get_session(int(row["id"])) for row in rows]

    def get_session(self, session_id: int) -> SessionSummary:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT s.*, ss.settings_json
                FROM sessions s
                JOIN session_settings ss ON ss.session_id = s.id
                WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown session id: {session_id}")
            stats = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS record_count,
                    COALESCE(SUM(CASE WHEN is_good = 1 THEN 1 ELSE 0 END), 0) AS good_count,
                    MIN(score) AS best_score
                FROM records
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            latest = self._conn.execute(
                """
                SELECT kp, ki, kd
                FROM records
                WHERE session_id = ?
                ORDER BY iteration_index DESC, id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()

        settings = json.loads(str(row["settings_json"]))
        current_pid = (
            PIDParams(kp=float(latest["kp"]), ki=float(latest["ki"]), kd=float(latest["kd"]))
            if latest is not None
            else _pid_from_payload(settings.get("current_pid") or {})
        )
        return SessionSummary(
            id=int(row["id"]),
            name=str(row["name"]),
            loop_name=str(row["loop_name"]),
            mode=str(row["mode"]),
            strategy=str(row["strategy"]),
            status=str(row["status"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            record_count=int(stats["record_count"] or 0),
            good_count=int(stats["good_count"] or 0),
            best_score=float(stats["best_score"]) if stats["best_score"] is not None else None,
            current_pid=current_pid,
            settings=settings,
        )

    def update_session(
        self,
        session_id: int,
        *,
        name: str | None = None,
        strategy: str | None = None,
        status: str | None = None,
        notes: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> SessionSummary:
        with self._lock, self._conn:
            session = self.get_session(session_id)
            new_name = name if name is not None else session.name
            new_strategy = strategy if strategy is not None else session.strategy
            new_status = status if status is not None else session.status
            new_notes = notes if notes is not None else session.notes
            new_settings = settings if settings is not None else session.settings
            now = utc_now()
            self._conn.execute(
                """
                UPDATE sessions
                SET name = ?, strategy = ?, status = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, new_strategy, new_status, new_notes, now, session_id),
            )
            self._conn.execute(
                "UPDATE session_settings SET settings_json = ? WHERE session_id = ?",
                (json.dumps(new_settings, ensure_ascii=False), session_id),
            )
        return self.get_session(session_id)

    def delete_session(self, session_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def clear_records(self, session_id: int) -> None:
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM records WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )

    def list_records(self, session_id: int) -> list[SessionRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM records
                WHERE session_id = ?
                ORDER BY iteration_index ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def delete_record(self, record_id: int) -> int | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT session_id FROM records WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                return None
            session_id = int(row["session_id"])
            self._conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (utc_now(), session_id),
            )
        return session_id

    def add_record(
        self,
        *,
        session_id: int,
        iteration_index: int,
        source: str,
        applied: bool,
        strategy_name: str,
        model_used: str,
        prev_pid: PIDParams,
        pid: PIDParams,
        metrics: MetricSnapshot,
        score: float | None,
        is_good: bool | None,
        quality_label: str | None,
        reason: str = "",
        confidence: float = 0.0,
        expected_improvement: str = "",
        raw_data_path: str | None = None,
        note: str = "",
        strategy_metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        now = utc_now()
        metadata_json = json.dumps(strategy_metadata or {}, ensure_ascii=False)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO records(
                    session_id, iteration_index, source, applied, strategy_name, model_used,
                    prev_kp, prev_ki, prev_kd, kp, ki, kd,
                    overshoot_pct, settling_time_s, steady_state_error_pct, oscillation_count,
                    is_diverging, is_saturated, rise_time_s, peak_error, mean_abs_error, rms_error,
                    data_points, score, is_good, quality_label, reason, confidence,
                    expected_improvement, raw_data_path, note, strategy_metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    iteration_index,
                    source,
                    int(applied),
                    strategy_name,
                    model_used,
                    prev_pid.kp,
                    prev_pid.ki,
                    prev_pid.kd,
                    pid.kp,
                    pid.ki,
                    pid.kd,
                    metrics.overshoot_pct,
                    metrics.settling_time_s,
                    metrics.steady_state_error_pct,
                    int(metrics.oscillation_count),
                    int(metrics.is_diverging),
                    int(metrics.is_saturated),
                    metrics.rise_time_s,
                    metrics.peak_error,
                    metrics.mean_abs_error,
                    metrics.rms_error,
                    metrics.data_points,
                    score,
                    None if is_good is None else int(is_good),
                    quality_label,
                    reason,
                    confidence,
                    expected_improvement,
                    raw_data_path,
                    note,
                    metadata_json,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            record_id = int(cur.lastrowid)
        return self.get_record(record_id)

    def get_record(self, record_id: int) -> SessionRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM records WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown record id: {record_id}")
        return _row_to_record(row)

    def append_event(self, session_id: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "session_id": session_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": utc_now(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO events(session_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                    event["created_at"],
                ),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (event["created_at"], session_id),
            )
        return event

    def list_events(self, session_id: int, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_type, payload_json, created_at
                FROM events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in reversed(rows):
            events.append(
                {
                    "session_id": session_id,
                    "event_type": str(row["event_type"]),
                    "payload": json.loads(str(row["payload_json"])),
                    "created_at": str(row["created_at"]),
                }
            )
        return events

    def next_iteration_index(self, session_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(iteration_index), 0) AS max_iteration FROM records WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["max_iteration"]) + 1


def _pid_from_payload(payload: dict[str, Any]) -> PIDParams:
    return PIDParams(
        kp=float(payload.get("kp", 1.0)),
        ki=float(payload.get("ki", 0.1)),
        kd=float(payload.get("kd", 0.05)),
    )


def _row_to_record(row: sqlite3.Row) -> SessionRecord:
    metrics = MetricSnapshot(
        overshoot_pct=float(row["overshoot_pct"]),
        settling_time_s=float(row["settling_time_s"]),
        steady_state_error_pct=float(row["steady_state_error_pct"]),
        oscillation_count=int(_coerce_int(row["oscillation_count"])),
        is_diverging=bool(row["is_diverging"]),
        is_saturated=bool(row["is_saturated"]),
        rise_time_s=float(row["rise_time_s"]) if row["rise_time_s"] is not None else None,
        peak_error=float(row["peak_error"]) if row["peak_error"] is not None else None,
        mean_abs_error=float(row["mean_abs_error"]) if row["mean_abs_error"] is not None else None,
        rms_error=float(row["rms_error"]) if row["rms_error"] is not None else None,
        data_points=int(row["data_points"]) if row["data_points"] is not None else None,
    )
    return SessionRecord(
        id=int(row["id"]),
        session_id=int(row["session_id"]),
        iteration_index=int(row["iteration_index"]),
        source=str(row["source"]),
        applied=bool(row["applied"]),
        strategy_name=str(row["strategy_name"]),
        model_used=str(row["model_used"]),
        prev_pid=PIDParams(
            kp=float(row["prev_kp"]),
            ki=float(row["prev_ki"]),
            kd=float(row["prev_kd"]),
        ),
        pid=PIDParams(
            kp=float(row["kp"]),
            ki=float(row["ki"]),
            kd=float(row["kd"]),
        ),
        metrics=metrics,
        score=float(row["score"]) if row["score"] is not None else None,
        is_good=bool(row["is_good"]) if row["is_good"] is not None else None,
        quality_label=str(row["quality_label"]) if row["quality_label"] is not None else None,
        reason=str(row["reason"]),
        confidence=float(row["confidence"]),
        expected_improvement=str(row["expected_improvement"]),
        raw_data_path=str(row["raw_data_path"]) if row["raw_data_path"] is not None else None,
        note=str(row["note"]),
        strategy_metadata=json.loads(str(row["strategy_metadata_json"])),
        created_at=str(row["created_at"]),
    )


def _coerce_int(value: Any) -> int:
    if isinstance(value, bytes):
        return int.from_bytes(value, "little", signed=False)
    return int(value)
