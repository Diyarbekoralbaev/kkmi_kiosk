"""
SQLite-based store for kiosk voice sessions.

Records each WebSocket conversation: session_id, start/end timestamps,
duration, transcript, error, provider, model.

Used by kiosk_voice.py (write) and api/sessions.py (read).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_PATH_ENV = "KIOSK_SESSIONS_DB_PATH"
_DEFAULT_DB_PATH = "/app/project/data/kiosk_sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kiosk_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    duration_seconds INTEGER,
    transcript TEXT DEFAULT '',
    error TEXT,
    provider TEXT DEFAULT 'google_live',
    model TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kiosk_sessions_started ON kiosk_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_kiosk_sessions_session_id ON kiosk_sessions(session_id);
"""


@dataclass
class KioskSessionRecord:
    id: Optional[int]
    session_id: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[int]
    transcript: str
    error: Optional[str]
    provider: str
    model: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KioskSessionStore:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.getenv(_DB_PATH_ENV) or _DEFAULT_DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_session(
        self,
        session_id: str,
        provider: str = "google_live",
        model: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO kiosk_sessions
                    (session_id, started_at, provider, model)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, now, provider, model),
            )

    def append_transcript(self, session_id: str, text: str, speaker: str = "user") -> None:
        """Append text to the transcript. speaker is 'user' or 'assistant'."""
        if not text:
            return
        line = f"[{speaker}] {text}"
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT transcript FROM kiosk_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return
            existing = row["transcript"] or ""
            new = f"{existing}\n{line}" if existing else line
            c.execute(
                "UPDATE kiosk_sessions SET transcript = ? WHERE session_id = ?",
                (new, session_id),
            )

    def close_session(self, session_id: str, error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc)
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT started_at FROM kiosk_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return
            try:
                started = datetime.fromisoformat(row["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                duration = int((now - started).total_seconds())
            except Exception:
                duration = None
            c.execute(
                """
                UPDATE kiosk_sessions
                SET ended_at = ?, duration_seconds = ?, error = ?
                WHERE session_id = ?
                """,
                (now.isoformat(), duration, error, session_id),
            )

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        today_only: bool = False,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM kiosk_sessions"
        params: List[Any] = []
        if today_only:
            query += " WHERE DATE(started_at) = DATE('now')"
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM kiosk_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_metrics(self) -> Dict[str, Any]:
        """Dashboard metrics: today's sessions, avg duration, errors, last 5."""
        with self._conn() as c:
            today_count = c.execute(
                "SELECT COUNT(*) FROM kiosk_sessions WHERE DATE(started_at) = DATE('now')"
            ).fetchone()[0]

            avg_duration = c.execute(
                """
                SELECT AVG(duration_seconds) FROM kiosk_sessions
                WHERE DATE(started_at) = DATE('now') AND duration_seconds IS NOT NULL
                """
            ).fetchone()[0] or 0

            error_count = c.execute(
                """
                SELECT COUNT(*) FROM kiosk_sessions
                WHERE DATE(started_at) = DATE('now') AND error IS NOT NULL
                """
            ).fetchone()[0]

            total_count = c.execute("SELECT COUNT(*) FROM kiosk_sessions").fetchone()[0]

            recent_rows = c.execute(
                "SELECT * FROM kiosk_sessions ORDER BY started_at DESC LIMIT 5"
            ).fetchall()

            return {
                "today_sessions": today_count,
                "avg_duration_seconds": round(float(avg_duration), 1),
                "today_errors": error_count,
                "total_sessions": total_count,
                "recent_sessions": [dict(r) for r in recent_rows],
            }


# Singleton
_store: Optional[KioskSessionStore] = None


def get_store() -> KioskSessionStore:
    global _store
    if _store is None:
        _store = KioskSessionStore()
    return _store
