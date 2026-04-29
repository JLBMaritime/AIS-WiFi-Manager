"""Login / logout / change-password views.

Uses flask-login for session management.  All routes here are *public*
(GET /login, POST /login, GET /logout) **except** ``/change-password``
which requires an active session.

A ``before_request`` guard forces users with ``must_change_password=1`` to
visit ``/change-password`` before any other page.  This is what implements
the "force change on first login" requirement.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from flask import (flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from app import app, limiter, WebUser
from app.database import set_password, verify_password, get_user

log = logging.getLogger(__name__)

# Pages reachable without being logged in (besides /login itself).
_PUBLIC_ENDPOINTS = {'login', 'static'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_safe_next(target: str | None) -> bool:
    """Avoid open-redirects: only same-host relative paths."""
    if not target:
        return False
    parsed = urlparse(target)
    return (not parsed.netloc) and parsed.path.startswith('/')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if verify_password(username, password):
            row = get_user(username) or {}
            user = WebUser(username, row.get('must_change_password', 0))
            login_user(user, remember=False)
            log.info("User '%s' logged in from %s", username,
                     request.remote_addr)
            nxt = request.args.get('next') or request.form.get('next')
            if _is_safe_next(nxt):
                return redirect(nxt)
            return redirect(url_for('index'))
        log.warning("Failed login for '%s' from %s", username,
                    request.remote_addr)
        flash('Invalid username or password.', 'error')

    return render_template('login.html', next=request.args.get('next', ''))


@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        log.info("User '%s' logged out", current_user.username)
        logout_user()
    return redirect(url_for('login'))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password') or ''
        new1    = request.form.get('new_password') or ''
        new2    = request.form.get('confirm_password') or ''

        if not verify_password(current_user.username, current):
            flash('Current password is incorrect.', 'error')
        elif len(new1) < 8:
            flash('New password must be at least 8 characters.', 'error')
        elif new1 != new2:
            flash('New passwords do not match.', 'error')
        elif new1 == current:
            flash('New password must be different from the current one.', 'error')
        else:
            set_password(current_user.username, new1, must_change=False)
            current_user.must_change_password = False
            flash('Password updated.', 'success')
            log.info("User '%s' changed password", current_user.username)
            return redirect(url_for('index'))

    return render_template('change_password.html',
                           force=current_user.must_change_password)


# ---------------------------------------------------------------------------
# Force first-login password change for everyone with the flag set.
# ---------------------------------------------------------------------------
@app.before_request
def _enforce_password_change():
    if not current_user.is_authenticated:
        return None
    if not getattr(current_user, 'must_change_password', False):
        return None
    if request.endpoint in {'change_password', 'logout', 'static'}:
        return None
    return redirect(url_for('change_password'))
