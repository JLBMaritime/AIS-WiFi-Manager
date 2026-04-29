"""SQLite persistence.

Two tables:

* ``saved_networks`` — the legacy "remember which Wi-Fi I've used" list.
* ``users``          — bcrypt-hashed credentials for the web UI.

A single module-level connection is opened with WAL + ``synchronous=NORMAL``
so the hot path (e.g. ``add_saved_network``) doesn't fsync per call and the
SD-card thanks us for it.  The connection is shared across threads
(``check_same_thread=False``); every write is wrapped in ``self._lock``.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional

import bcrypt

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution — installed dir first, fall back to CWD for development.
# ---------------------------------------------------------------------------
def get_db_path() -> str:
    installed = '/opt/ais-wifi-manager/wifi_manager.db'
    if os.path.isdir('/opt/ais-wifi-manager'):
        # Make sure parent exists so we never silently fall back to '/'.
        try:
            os.makedirs(os.path.dirname(installed), exist_ok=True)
        except OSError as exc:  # pragma: no cover
            log.warning("Could not create %s: %s", os.path.dirname(installed),
                        exc)
        return installed
    return os.path.abspath('wifi_manager.db')


DB_PATH = get_db_path()

DEFAULT_USER = "JLBMaritime"
DEFAULT_PASSWORD = "Admin"


# ---------------------------------------------------------------------------
# Connection singleton
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                _conn = _connect()
    return _conn


# ---------------------------------------------------------------------------
# Schema + seeding
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create tables if missing and seed the default user."""
    conn = get_conn()
    with _lock:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS saved_networks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ssid         TEXT UNIQUE NOT NULL,
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS users (
                username             TEXT PRIMARY KEY,
                password_hash        TEXT NOT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    seed_default_user()


def seed_default_user() -> None:
    """Insert the install-default user if the table is empty."""
    conn = get_conn()
    with _lock:
        cur = conn.execute("SELECT COUNT(*) AS n FROM users")
        if cur.fetchone()["n"] == 0:
            pw_hash = bcrypt.hashpw(DEFAULT_PASSWORD.encode("utf-8"),
                                    bcrypt.gensalt(rounds=12)).decode("ascii")
            conn.execute(
                "INSERT INTO users(username, password_hash, must_change_password) "
                "VALUES (?, ?, 1)",
                (DEFAULT_USER, pw_hash),
            )
            conn.commit()
            log.info("Seeded default user '%s' (forced password change on first login)",
                     DEFAULT_USER)


# ---------------------------------------------------------------------------
# Saved-networks API (unchanged signatures for backwards-compat)
# ---------------------------------------------------------------------------
def add_saved_network(ssid: str) -> None:
    if not ssid:
        return
    conn = get_conn()
    now = datetime.now()
    try:
        with _lock:
            conn.execute("""
                INSERT INTO saved_networks (ssid, connected_at, last_used)
                VALUES (?, ?, ?)
                ON CONFLICT(ssid) DO UPDATE SET last_used = excluded.last_used
            """, (ssid, now, now))
            conn.commit()
    except sqlite3.Error as exc:
        log.warning("add_saved_network(%r) failed: %s", ssid, exc)


def get_saved_networks() -> List[dict]:
    conn = get_conn()
    with _lock:
        rows = conn.execute("""
            SELECT ssid, connected_at, last_used
            FROM saved_networks
            ORDER BY last_used DESC
        """).fetchall()
    return [{'ssid': r['ssid'],
             'connected_at': r['connected_at'],
             'last_used': r['last_used']} for r in rows]


def forget_network(ssid: str) -> bool:
    if not ssid:
        return False
    conn = get_conn()
    try:
        with _lock:
            conn.execute("DELETE FROM saved_networks WHERE ssid = ?", (ssid,))
            conn.commit()
        return True
    except sqlite3.Error as exc:
        log.warning("forget_network(%r) failed: %s", ssid, exc)
        return False


def network_exists(ssid: str) -> bool:
    conn = get_conn()
    with _lock:
        cur = conn.execute("SELECT 1 FROM saved_networks WHERE ssid = ?",
                           (ssid,))
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Users API
# ---------------------------------------------------------------------------
def get_user(username: str) -> Optional[dict]:
    conn = get_conn()
    with _lock:
        row = conn.execute(
            "SELECT username, password_hash, must_change_password "
            "FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def verify_password(username: str, password: str) -> bool:
    """Constant-time check; returns False on missing user too."""
    user = get_user(username)
    if not user:
        # Still hash *something* so timing doesn't reveal valid usernames.
        bcrypt.checkpw(b"x", bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4)))
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              user["password_hash"].encode("ascii"))
    except (ValueError, TypeError):
        return False


def set_password(username: str, new_password: str,
                 must_change: bool = False) -> bool:
    if not new_password or len(new_password) < 8:
        return False
    pw_hash = bcrypt.hashpw(new_password.encode("utf-8"),
                            bcrypt.gensalt(rounds=12)).decode("ascii")
    conn = get_conn()
    with _lock:
        conn.execute("""
            UPDATE users
            SET password_hash = ?, must_change_password = ?, updated_at = ?
            WHERE username = ?
        """, (pw_hash, 1 if must_change else 0, datetime.now(), username))
        conn.commit()
    return True


def reset_user_to_default(username: str = DEFAULT_USER) -> None:
    """Restore the default password and force a change on next login."""
    conn = get_conn()
    pw_hash = bcrypt.hashpw(DEFAULT_PASSWORD.encode("utf-8"),
                            bcrypt.gensalt(rounds=12)).decode("ascii")
    with _lock:
        conn.execute("""
            INSERT INTO users (username, password_hash, must_change_password)
            VALUES (?, ?, 1)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                must_change_password = 1,
                updated_at = CURRENT_TIMESTAMP
        """, (username, pw_hash))
        conn.commit()
    log.warning("User '%s' reset to default password (forced change on next login)",
                username)
