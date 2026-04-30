"""
ais-hotspot-watchdog
====================

Tiny self-healing supervisor for the always-on `ais-hotspot` AP profile.

Run as its own systemd unit (see service/ais-hotspot-watchdog.service).
Deliberately stdlib-only so it can recover even if the venv's
site-packages are wedged.

Operational contract
--------------------
* Polls `nmcli -t -f NAME,STATE c show --active` every POLL_INTERVAL s.
* If `ais-hotspot` is missing from the active list (or in any
  non-`activated` state) for >= POLL_FAIL_SECS, attempt
  `nmcli c up ais-hotspot`.
* Backoff between attempts: 5, 10, 20, 40, 80, 160, 300 s (capped).
* Logs every state transition to journald with structured prefixes
  (HOTSPOT_DOWN, HOTSPOT_RECOVERED, NMCLI_FAIL) so an operator can:
      journalctl -u ais-hotspot-watchdog --grep RECOVERED
* Exits 0 only on SIGTERM/SIGINT.  Any uncaught exception → exit 1
  → systemd restarts us via `Restart=always`.

What it deliberately does NOT do
--------------------------------
* It does not try to "fix" the underlying USB / firmware issue — that
  belongs at install time (USB-3 detector) and at diagnose time
  (`ais-wifi-cli doctor`).  The watchdog is the bottom-of-the-funnel
  recovery; surfacing the loud root cause is somebody else's job.
* It does not restart NetworkManager.  Repeatedly bouncing NM is far
  more disruptive than a stuck AP — wlan0 (the user's internet uplink)
  would die with it.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Tunables — environment-overridable for testing.  Defaults chosen for
# fast self-heal without thrashing nmcli.
# ---------------------------------------------------------------------------
HOTSPOT_NAME: str = os.environ.get("AIS_HOTSPOT_NAME", "ais-hotspot")
POLL_INTERVAL: float = float(os.environ.get("AIS_WATCHDOG_POLL", "5"))
POLL_FAIL_SECS: float = float(os.environ.get("AIS_WATCHDOG_FAIL_SECS", "15"))
BACKOFF_SCHEDULE = (5, 10, 20, 40, 80, 160, 300)  # seconds, capped at last
NMCLI_TIMEOUT: float = 30.0
# ---------------------------------------------------------------------------


_stop = False


def _on_signal(signum, _frame):  # noqa: D401, ANN001
    """SIGTERM / SIGINT handler — flips the stop flag for clean exit."""
    global _stop
    _stop = True
    log("STOP", f"received signal {signum}; exiting cleanly")


def log(tag: str, msg: str) -> None:
    """journald gets one line per event, prefix-tagged for easy grep."""
    # Don't use logging.* — we want exact, immediate lines on stdout
    # so journald's SyslogIdentifier picks them up unambiguously.
    sys.stdout.write(f"{tag}: {msg}\n")
    sys.stdout.flush()


def run_nmcli(args: list[str]) -> tuple[int, str]:
    """
    Run nmcli with a hard timeout.  Returns (rc, combined_stdout_stderr).
    Never raises — a wedged nmcli must not crash the watchdog.
    """
    cmd = ["nmcli", *args]
    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=NMCLI_TIMEOUT,
            check=False,
        )
        return cp.returncode, (cp.stdout + cp.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {NMCLI_TIMEOUT}s: {shlex.join(cmd)}"
    except FileNotFoundError:
        return 127, "nmcli not found in PATH"
    except OSError as exc:
        return 1, f"OSError: {exc!r}"


def hotspot_state() -> Optional[str]:
    """
    Returns the activation-state string ('activated', 'activating',
    'deactivating', etc.) for HOTSPOT_NAME, or None if not active at all.

    Uses `nmcli -t -f NAME,STATE c show --active` so we don't rely on
    column-width parsing and field ordering.
    """
    rc, out = run_nmcli(["-t", "-f", "NAME,STATE", "c", "show", "--active"])
    if rc != 0:
        log("NMCLI_FAIL", f"show --active rc={rc}: {out}")
        return None
    for line in out.splitlines():
        # Format: NAME:STATE  (':'-escaped if NAME contains ':', but
        # ais-hotspot won't — keep this simple).
        if ":" not in line:
            continue
        name, _, state = line.partition(":")
        if name == HOTSPOT_NAME:
            return state.strip().lower() or "unknown"
    return None


def attempt_recover(attempt: int) -> bool:
    """One-shot recovery: `nmcli c up <hotspot>` + verify."""
    log("RECOVER", f"attempt {attempt}: nmcli c up {HOTSPOT_NAME}")
    rc, out = run_nmcli(["c", "up", HOTSPOT_NAME])
    if rc != 0:
        log("NMCLI_FAIL", f"up rc={rc}: {out}")
        return False
    # nmcli can return 0 even when activation is still in progress.
    # Re-check the state.
    for _ in range(10):
        if _stop:
            return False
        time.sleep(1)
        if hotspot_state() == "activated":
            return True
    return False


def main() -> int:  # pragma: no cover - entry point
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    log("START", f"watchdog up; target='{HOTSPOT_NAME}' "
                 f"poll={POLL_INTERVAL}s fail_after={POLL_FAIL_SECS}s")

    last_good = time.monotonic()
    last_state: Optional[str] = None
    attempt = 0
    next_recover_after: float = 0.0  # monotonic deadline

    while not _stop:
        state = hotspot_state()
        now = time.monotonic()

        if state != last_state:
            log("STATE", f"{HOTSPOT_NAME}: {last_state!r} -> {state!r}")
            last_state = state

        if state == "activated":
            if attempt:
                log("RECOVERED",
                    f"{HOTSPOT_NAME} active again after {attempt} attempt(s)")
            attempt = 0
            next_recover_after = 0.0
            last_good = now
        else:
            # Has the AP been down long enough to act?
            down_for = now - last_good
            if down_for >= POLL_FAIL_SECS and now >= next_recover_after:
                attempt += 1
                if attempt == 1:
                    log("HOTSPOT_DOWN",
                        f"{HOTSPOT_NAME} not activated for {down_for:.1f}s; "
                        f"starting recovery")
                ok = attempt_recover(attempt)
                if ok:
                    last_state = "activated"
                    log("RECOVERED",
                        f"{HOTSPOT_NAME} active again after {attempt} "
                        f"attempt(s)")
                    attempt = 0
                    next_recover_after = 0.0
                    last_good = time.monotonic()
                else:
                    delay = BACKOFF_SCHEDULE[
                        min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
                    ]
                    next_recover_after = time.monotonic() + delay
                    log("BACKOFF",
                        f"recovery attempt {attempt} failed; "
                        f"next try in {delay}s")

        # Sleep in small increments so SIGTERM is honoured promptly.
        slept = 0.0
        while slept < POLL_INTERVAL and not _stop:
            time.sleep(0.5)
            slept += 0.5

    log("STOP", "watchdog exiting cleanly")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
