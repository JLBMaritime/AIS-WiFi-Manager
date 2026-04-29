"""Shared subprocess helpers.

Centralised so we can:

* enforce ``shell=False`` everywhere (no shell-injection from SSIDs / IPs),
* enforce a default timeout,
* keep one consistent return-tuple shape.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Iterable, Tuple

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


def run_args(args: Iterable[str],
             timeout: float = DEFAULT_TIMEOUT,
             input_text: str | None = None) -> Tuple[str, str, int]:
    """Run *args* (a list/tuple) without a shell.

    Returns ``(stdout, stderr, returncode)``.  On timeout / OSError the
    return-code is non-zero and the error message is in *stderr*.
    """
    args = list(args)
    if not args:
        return "", "empty command", 1
    # Friendlier error than FileNotFoundError if the binary is missing.
    if shutil.which(args[0]) is None and "/" not in args[0]:
        return "", f"{args[0]}: command not found", 127
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", f"{args[0]}: command timed out after {timeout:.0f}s", 124
    except OSError as exc:
        return "", str(exc), 1


def have(binary: str) -> bool:
    """Return True if *binary* exists on PATH."""
    return shutil.which(binary) is not None
