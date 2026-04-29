"""Flask application factory.

* Persistent ``SECRET_KEY`` (per-install, in
  ``/opt/ais-wifi-manager/secret_key`` or ``./secret_key`` for dev).  Random
  on first run only — restarting the service no longer invalidates every
  active session.
* ``flask-login`` for a real login flow (page-based, not HTTP-Basic).
* ``flask-limiter`` rate-limits the login endpoint at 5/min/IP.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistent secret-key loader
# ---------------------------------------------------------------------------
def _secret_key_path() -> Path:
    installed = Path('/opt/ais-wifi-manager/secret_key')
    if installed.parent.is_dir():
        return installed
    return Path('secret_key').resolve()


def _load_or_create_secret_key() -> bytes:
    p = _secret_key_path()
    try:
        if p.exists():
            data = p.read_bytes().strip()
            if len(data) >= 32:
                return data
        # Generate, persist with chmod 600.
        data = secrets.token_bytes(48)
        p.write_bytes(data)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        log.info("Generated new SECRET_KEY at %s", p)
        return data
    except OSError as exc:
        # Read-only filesystem etc. — fall back to a *process-lifetime* key.
        log.warning("Could not persist SECRET_KEY (%s); using ephemeral key",
                    exc)
        return secrets.token_bytes(48)


# ---------------------------------------------------------------------------
# App + extensions
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_or_create_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,   # 8 h
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.session_protection = 'basic'

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],          # only applied where we explicitly decorate
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# User loader (lazy import to avoid circulars)
# ---------------------------------------------------------------------------
class WebUser:
    """Minimal flask-login User."""
    def __init__(self, username: str, must_change_password: bool):
        self.id = username
        self.username = username
        self.must_change_password = bool(must_change_password)

    @property
    def is_authenticated(self): return True
    @property
    def is_active(self):        return True
    @property
    def is_anonymous(self):     return False
    def get_id(self):           return self.username


@login_manager.user_loader
def _load_user(username: str):
    from app.database import get_user
    row = get_user(username)
    if not row:
        return None
    return WebUser(row['username'], row['must_change_password'])


# Register routes / auth blueprint.
from app import auth      # noqa: E402, F401  (registers /login, /logout, …)
from app import routes    # noqa: E402, F401
