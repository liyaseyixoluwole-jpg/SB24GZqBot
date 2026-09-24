"""
SQLite persistence layer for reminders.
"""
import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "reminders.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables/indexes if they don't exist."""
    # Ensure parent directory exists (Railway volume: /data)
    parent = os.path.dirname(DB_PATH)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                text         TEXT    NOT NULL,
                remind_at    TEXT    NOT NULL,
                repeat_type  TEXT    NOT NULL DEFAULT 'none',
                repeat_value INTEGER NOT NULL DEFAULT 0,
                is_active    INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_time "
            "ON reminders(is_active, remind_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user "
            "ON reminders(user_id, is_active)"
        )
        conn.commit()


def add_reminder(
    chat_id: int,
    user_id: int,
    text: str,
    remind_at: datetime,
    repeat_type: str = "none",
    repeat_value: int = 0,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reminders
                (chat_id, user_id, text, remind_at, repeat_type, repeat_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                user_id,
                text,
                remind_at.isoformat(),
                repeat_type,
                repeat_value,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_user_reminders(user_id: int) -> List[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT id, text, remind_at, repeat_type, repeat_value
            FROM reminders
            WHERE user_id = ? AND is_active = 1
            ORDER BY remind_at ASC
            """,
            (user_id,),
        )
        return cur.fetchall()


def get_reminder(reminder_id: int, user_id: int) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        return cur.fetchone()


def delete_reminder(reminder_id: int, user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE reminders SET is_active = 0 WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_reminder_time(reminder_id: int, new_time: datetime) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE reminders SET remind_at = ? WHERE id = ?",
            (new_time.isoformat(), reminder_id),
        )
        conn.commit()


def get_due_reminders(now_iso: str) -> List[sqlite3.Row]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT id, chat_id, user_id, text, remind_at, repeat_type, repeat_value
            FROM reminders
            WHERE is_active = 1 AND remind_at <= ?
            """,
            (now_iso,),
        )
        return cur.fetchall()
