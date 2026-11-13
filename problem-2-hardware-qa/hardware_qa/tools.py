from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from .allowlist import AllowlistError, ValidatedCommand, validate_command


@dataclass
class ToolResult:
    command: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_allowlisted(
    command: str | list[str],
    *,
    runner: Runner | None = None,
) -> ToolResult:
    """Validate then execute. Never passes the string to a shell."""
    try:
        validated: ValidatedCommand = validate_command(command)
    except AllowlistError as exc:
        return ToolResult(
            command=command if isinstance(command, str) else " ".join(command),
            ok=False,
            stdout="",
            stderr="",
            exit_code=126,
            error=str(exc),
        )

    run = runner or _default_runner
    # Skip PATH check when a custom runner is injected (unit tests / fakes).
    if runner is None and shutil.which(validated.binary) is None:
        return ToolResult(
            command=" ".join(validated.argv),
            ok=False,
            stdout="",
            stderr="",
            exit_code=127,
            error=f"tool not installed: {validated.binary}",
        )

    try:
        proc = run(validated.argv)
    except subprocess.TimeoutExpired:
        return ToolResult(
            command=" ".join(validated.argv),
            ok=False,
            stdout="",
            stderr="",
            exit_code=124,
            error="command timed out",
        )
    except OSError as exc:
        return ToolResult(
            command=" ".join(validated.argv),
            ok=False,
            stdout="",
            stderr="",
            exit_code=1,
            error=str(exc),
        )

    return ToolResult(
        command=" ".join(validated.argv),
        ok=proc.returncode == 0,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        exit_code=proc.returncode,
        error=None if proc.returncode == 0 else (proc.stderr or f"exit {proc.returncode}"),
    )


# Named tools the agent can request by intent key.
TOOL_CATALOG: dict[str, dict] = {
    "cpu": {
        "description": "CPU model, cores, architecture",
        "commands": ["lscpu", "nproc", "cat /proc/cpuinfo"],
    },
    "memory": {
        "description": "Installed and available RAM",
        "commands": ["free -h", "cat /proc/meminfo"],
    },
    "memory_slots": {
        "description": "DIMM slots / max capacity (may need root for dmidecode)",
        "commands": ["dmidecode -t memory"],
    },
    "storage": {
        "description": "Block devices, SSD/HDD, NVMe",
        # -P (key=value) is unambiguous when MODEL is empty; -o limits columns.
        "commands": [
            "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT"
        ],
    },
    "pci": {
        "description": "PCI devices including GPU",
        "commands": ["lspci"],
    },
    "system": {
        "description": "Kernel and product identity",
        "commands": [
            "uname -a",
            "cat /sys/class/dmi/id/sys_vendor",
            "cat /sys/class/dmi/id/product_name",
        ],
    },
    "disk_space": {
        "description": "Filesystem usage",
        "commands": ["df -hT"],
    },
}
