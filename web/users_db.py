"""User account management: maps display names to stable UUIDs.

Special case: the display name "user" is the legacy default identity.
It maps to user_id="user" (identity mapping, no real UUID) so that
existing sessions stored with user_id="user" continue to work without
any database migration.

All other display names get a uuid4 on first login (lazy creation).
Optionally, accounts can be password-protected via bcrypt.
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from pathlib import Path

import bcrypt

USERS_DB_PATH = Path(__file__).parent / "users.db"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

LEGACY_USER = "user"


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


def _is_valid_identity(s: str) -> bool:
    """Return True if s is already a stable identity (UUID or the special 'user' name)."""
    return s == LEGACY_USER or _is_uuid(s)


def init_db() -> None:
    with sqlite3.connect(USERS_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                display_name  TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                created_at    REAL NOT NULL
            )
        """)
        conn.commit()


def get_by_display_name(display_name: str) -> dict | None:
    with sqlite3.connect(USERS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE display_name = ?", (display_name,)
        ).fetchone()
    return dict(row) if row else None


def get_by_id(user_id: str) -> dict | None:
    if user_id == LEGACY_USER:
        return {"id": LEGACY_USER, "display_name": LEGACY_USER, "password_hash": None}
    with sqlite3.connect(USERS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def create_user(display_name: str, password: str | None = None) -> dict:
    user_id = str(uuid.uuid4())
    password_hash = _hash(password) if password else None
    with sqlite3.connect(USERS_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, display_name, password_hash, time.time()),
        )
        conn.commit()
    return {"id": user_id, "display_name": display_name, "password_hash": password_hash}


def set_password(user_id: str, new_password: str) -> None:
    with sqlite3.connect(USERS_DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash(new_password), user_id),
        )
        conn.commit()


def verify_password(stored_hash: str | None, password: str | None) -> bool:
    if stored_hash is None:
        return True  # no password set — always passes
    if not password:
        return False
    return bcrypt.checkpw(password.encode(), stored_hash.encode())


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def migrate_legacy_adk_sessions(session_db_path: Path, app_name: str) -> None:
    """Migrate non-UUID, non-'user' user_id values in the ADK session.db to UUIDs.

    This handles the rare case where someone used a custom display name
    (not 'user') before this UUID system was introduced.
    """
    if not session_db_path.exists():
        return

    try:
        with sqlite3.connect(session_db_path) as adk_conn:
            rows = adk_conn.execute(
                "SELECT DISTINCT user_id FROM sessions WHERE app_name = ?",
                (app_name,),
            ).fetchall()
            old_ids = [r[0] for r in rows if not _is_valid_identity(r[0])]

        for old_id in old_ids:
            try:
                _migrate_one(session_db_path, app_name, old_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[users_db] migration warning for {old_id!r}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"[users_db] migration skipped: {exc}")


def _migrate_one(session_db_path: Path, app_name: str, old_id: str) -> None:
    # Reuse existing users row if display name already registered, else create.
    existing = get_by_display_name(old_id)
    if existing:
        new_id = existing["id"]
    else:
        new_id = str(uuid.uuid4())
        with sqlite3.connect(USERS_DB_PATH) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, display_name, password_hash, created_at) VALUES (?, ?, NULL, ?)",
                (new_id, old_id, time.time()),
            )
            conn.commit()

    with sqlite3.connect(session_db_path) as adk_conn:
        adk_conn.execute(
            "UPDATE sessions SET user_id = ? WHERE app_name = ? AND user_id = ?",
            (new_id, app_name, old_id),
        )
        adk_conn.execute(
            "UPDATE events SET user_id = ? WHERE app_name = ? AND user_id = ?",
            (new_id, app_name, old_id),
        )
        for tbl in ("user_states",):
            try:
                adk_conn.execute(
                    f"UPDATE {tbl} SET user_id = ? WHERE app_name = ? AND user_id = ?",
                    (new_id, app_name, old_id),
                )
            except sqlite3.OperationalError:
                pass  # table may not exist in all ADK versions
        adk_conn.commit()
    print(f"[users_db] migrated {old_id!r} → {new_id}")
