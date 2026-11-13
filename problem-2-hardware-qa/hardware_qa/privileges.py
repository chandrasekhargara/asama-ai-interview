"""
Privilege strategies for tools that need elevated access (e.g. dmidecode).

Matching the Notion engineering guide:

  A. Scoped sudoers for specific binaries (recommended for CLI demos)
  B. Privileged helper daemon over a Unix socket (enterprise)
  C. Non-root fallbacks via /proc /sys lscpu lsblk lspci (zero-install)

The LLM never chooses sudo or a shell — it only selects tool *names*.
Privilege escalation is applied inside the executor.
"""

from __future__ import annotations

import os
import shutil
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PrivilegeStrategy(str, Enum):
    SCOPED_SUDO = "A_scoped_sudo"
    HELPER_DAEMON = "B_helper_daemon"
    NON_ROOT_FALLBACK = "C_non_root_fallback"


@dataclass
class PrivilegeResolution:
    strategy: PrivilegeStrategy
    argv: list[str]
    note: str
    used_elevation: bool = False
    fallback_tool: Optional[str] = None


def preferred_strategy() -> PrivilegeStrategy:
    env = os.environ.get("HARDWARE_QA_PRIVILEGE", "").strip().upper()
    if env in {"A", "SUDO", "A_SCOPED_SUDO"}:
        return PrivilegeStrategy.SCOPED_SUDO
    if env in {"B", "HELPER", "B_HELPER_DAEMON"}:
        return PrivilegeStrategy.HELPER_DAEMON
    if env in {"C", "FALLBACK", "C_NON_ROOT_FALLBACK"}:
        return PrivilegeStrategy.NON_ROOT_FALLBACK
    # Auto: prefer sudo when available, else fallback.
    if shutil.which("sudo"):
        return PrivilegeStrategy.SCOPED_SUDO
    return PrivilegeStrategy.NON_ROOT_FALLBACK


def resolve_root_argv(
    base_argv: list[str],
    *,
    strategy: PrivilegeStrategy | None = None,
    fallback_tool: str | None = None,
) -> PrivilegeResolution:
    """
    Turn a root-requiring tool argv into an executable plan.

    Strategy A example sudoers note (operator-installed, not shipped here):
      youruser ALL=(root) NOPASSWD: /usr/sbin/dmidecode -t memory
    """
    strategy = strategy or preferred_strategy()
    binary = base_argv[0]

    if strategy == PrivilegeStrategy.SCOPED_SUDO:
        sudo = shutil.which("sudo")
        # Prefer absolute path for the binary when present (matches sudoers).
        resolved = shutil.which(binary) or binary
        if sudo:
            argv = [sudo, "-n", resolved, *base_argv[1:]]
            return PrivilegeResolution(
                strategy=strategy,
                argv=argv,
                note=(
                    "Strategy A: scoped sudo -n. Install a sudoers rule limited to "
                    f"`{resolved} {' '.join(base_argv[1:])}` (NOPASSWD)."
                ),
                used_elevation=True,
            )
        # Fall through to C if sudo missing
        strategy = PrivilegeStrategy.NON_ROOT_FALLBACK

    if strategy == PrivilegeStrategy.HELPER_DAEMON:
        sock_path = os.environ.get(
            "HARDWARE_QA_HELPER_SOCK", "/run/hardware-qa/helper.sock"
        )
        if _helper_socket_alive(sock_path):
            # Executor talks to the helper; argv is a sentinel the runner understands.
            return PrivilegeResolution(
                strategy=strategy,
                argv=["__helper__", sock_path, *base_argv],
                note=(
                    "Strategy B: privileged helper daemon over Unix socket "
                    f"{sock_path}."
                ),
                used_elevation=True,
            )
        strategy = PrivilegeStrategy.NON_ROOT_FALLBACK

    # Strategy C — no elevation; caller should switch to fallback tool.
    return PrivilegeResolution(
        strategy=PrivilegeStrategy.NON_ROOT_FALLBACK,
        argv=list(base_argv),
        note=(
            "Strategy C: non-root fallback. dmidecode/root tools may fail; "
            "use /proc /sys and allow-listed user tools instead."
        ),
        used_elevation=False,
        fallback_tool=fallback_tool,
    )


def _helper_socket_alive(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(path)
        sock.close()
        return True
    except OSError:
        return False


STRATEGY_DOCS = {
    PrivilegeStrategy.SCOPED_SUDO: (
        "A — Scoped sudoers: allow only specific argv (e.g. dmidecode -t memory). "
        "Best for laptop CLI demos."
    ),
    PrivilegeStrategy.HELPER_DAEMON: (
        "B — Privileged helper daemon: a root service exposes a Unix socket; "
        "the unprivileged agent sends tool-name requests. Enterprise-friendly."
    ),
    PrivilegeStrategy.NON_ROOT_FALLBACK: (
        "C — Non-root fallbacks: lscpu, lsblk, free, lspci, /proc, /sys. "
        "Zero-install; say 'unavailable' when slot/max-capacity needs DMI."
    ),
}
