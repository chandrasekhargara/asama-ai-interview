from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .allowlist import AllowlistError, ValidatedCommand, validate_command
from .privileges import PrivilegeStrategy, resolve_root_argv


@dataclass
class ToolResult:
    command: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None
    tool_name: str | None = None
    privilege_note: str | None = None


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ToolSpec:
    """Allow-listed tool the model may select by name (never raw shell)."""

    name: str
    description: str
    argv: tuple[str, ...]
    privilege: str = "none"  # none | root
    fallbacks: tuple[str, ...] = ()
    schema: dict[str, Any] = field(default_factory=dict)


# Guide-aligned tool names. argv is fixed — LLM cannot alter flags.
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "get_cpu_info": ToolSpec(
        name="get_cpu_info",
        description="CPU model, cores, architecture via lscpu",
        argv=("lscpu",),
    ),
    "get_block_devices": ToolSpec(
        name="get_block_devices",
        description="Block devices as JSON (lsblk -J)",
        argv=(
            "lsblk",
            "-J",
            "-o",
            "NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT",
        ),
    ),
    "get_memory_summary": ToolSpec(
        name="get_memory_summary",
        description="Installed/available RAM via free -b",
        argv=("free", "-b"),
    ),
    "get_meminfo": ToolSpec(
        name="get_meminfo",
        description="Non-root /proc/meminfo fallback",
        argv=("cat", "/proc/meminfo"),
    ),
    "get_dmi_memory": ToolSpec(
        name="get_dmi_memory",
        description="DMI memory array / DIMM slots (may need root)",
        argv=("dmidecode", "-t", "memory"),
        privilege="root",
        fallbacks=("get_meminfo", "get_memory_summary"),
        schema={"include_empty_slots": {"type": "boolean", "default": True}},
    ),
    "get_memory_topology": ToolSpec(
        name="get_memory_topology",
        description="Alias for DMI memory topology (slots + max capacity)",
        argv=("dmidecode", "-t", "memory"),
        privilege="root",
        fallbacks=("get_meminfo", "get_memory_summary"),
        schema={"include_empty_slots": {"type": "boolean", "default": True}},
    ),
    "get_pci_devices": ToolSpec(
        name="get_pci_devices",
        description="PCI devices including GPU via lspci",
        argv=("lspci",),
    ),
    "get_system_uname": ToolSpec(
        name="get_system_uname",
        description="Kernel identity",
        argv=("uname", "-a"),
    ),
    "get_system_vendor": ToolSpec(
        name="get_system_vendor",
        description="DMI sys_vendor (non-root sysfs)",
        argv=("cat", "/sys/class/dmi/id/sys_vendor"),
    ),
    "get_system_product": ToolSpec(
        name="get_system_product",
        description="DMI product_name (non-root sysfs)",
        argv=("cat", "/sys/class/dmi/id/product_name"),
    ),
    "get_disk_space": ToolSpec(
        name="get_disk_space",
        description="Filesystem usage",
        argv=("df", "-hT"),
    ),
    "get_nproc": ToolSpec(
        name="get_nproc",
        description="Logical CPU count",
        argv=("nproc",),
    ),
}

# Intent → ordered tool names (model/classifier picks from this allow-list).
INTENT_TOOLS: dict[str, list[str]] = {
    "cpu": ["get_cpu_info", "get_nproc"],
    "memory": ["get_memory_summary", "get_meminfo"],
    "memory_slots": ["get_dmi_memory"],
    "storage": ["get_block_devices"],
    "pci": ["get_pci_devices"],
    "system": ["get_system_uname", "get_system_vendor", "get_system_product"],
    "disk_space": ["get_disk_space"],
}

# Backward-compat alias used by older docs/tests.
TOOL_CATALOG: dict[str, dict] = {
    intent: {
        "description": f"Tools for {intent}",
        "commands": [" ".join(TOOL_REGISTRY[n].argv) for n in names if n in TOOL_REGISTRY],
        "tools": names,
    }
    for intent, names in INTENT_TOOLS.items()
}


def list_tool_names() -> list[str]:
    return sorted(TOOL_REGISTRY)


def discover_available_tools() -> dict[str, bool]:
    """Capability discovery via shutil.which (guide talking point)."""
    out: dict[str, bool] = {}
    for name, spec in TOOL_REGISTRY.items():
        binary = spec.argv[0]
        out[name] = shutil.which(binary) is not None
    return out


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
    tool_name: str | None = None,
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
            tool_name=tool_name,
        )

    run = runner or _default_runner
    # Skip PATH check when a custom runner is injected (unit tests / fakes).
    check_bin = validated.binary
    if check_bin == "sudo" and len(validated.argv) >= 3:
        # For sudo, check the target exists when using absolute path or basename.
        target = validated.argv[2]
        target_base = target.rsplit("/", 1)[-1]
        if runner is None and shutil.which(target_base) is None and not (
            target.startswith("/") and __import__("os").path.exists(target)
        ):
            return ToolResult(
                command=" ".join(validated.argv),
                ok=False,
                stdout="",
                stderr="",
                exit_code=127,
                error=f"tool not installed: {target_base}",
                tool_name=tool_name,
            )
    elif runner is None and shutil.which(validated.binary) is None:
        return ToolResult(
            command=" ".join(validated.argv),
            ok=False,
            stdout="",
            stderr="",
            exit_code=127,
            error=f"tool not installed: {validated.binary}",
            tool_name=tool_name,
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
            tool_name=tool_name,
        )
    except OSError as exc:
        return ToolResult(
            command=" ".join(validated.argv),
            ok=False,
            stdout="",
            stderr="",
            exit_code=1,
            error=str(exc),
            tool_name=tool_name,
        )

    return ToolResult(
        command=" ".join(validated.argv),
        ok=proc.returncode == 0,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        exit_code=proc.returncode,
        error=None if proc.returncode == 0 else (proc.stderr or f"exit {proc.returncode}"),
        tool_name=tool_name,
    )


def run_named_tool(
    tool_name: str,
    *,
    runner: Runner | None = None,
    params: Optional[dict[str, Any]] = None,
    privilege_strategy: PrivilegeStrategy | None = None,
) -> ToolResult:
    """
    Execute a tool by allow-listed name. Optional params are schema-validated
    stubs (e.g. include_empty_slots) — they never become shell fragments.
    """
    if tool_name not in TOOL_REGISTRY:
        return ToolResult(
            command=tool_name,
            ok=False,
            stdout="",
            stderr="",
            exit_code=126,
            error=f"unknown tool name (not on allow-list): {tool_name}",
            tool_name=tool_name,
        )
    spec = TOOL_REGISTRY[tool_name]
    params = params or {}
    # Schema gate: reject unknown keys (anti-injection via "tool args").
    allowed_keys = set(spec.schema) | set()
    for key in params:
        if key not in allowed_keys:
            return ToolResult(
                command=" ".join(spec.argv),
                ok=False,
                stdout="",
                stderr="",
                exit_code=126,
                error=f"parameter not in tool schema: {key}",
                tool_name=tool_name,
            )

    argv = list(spec.argv)
    privilege_note = None
    # Fixture/unit-test runners supply canned output for the base argv —
    # skip live sudo/helper elevation so demos stay deterministic.
    if spec.privilege == "root" and runner is None:
        resolution = resolve_root_argv(
            argv,
            strategy=privilege_strategy,
            fallback_tool=spec.fallbacks[0] if spec.fallbacks else None,
        )
        privilege_note = resolution.note
        if resolution.used_elevation and resolution.argv[0] != "__helper__":
            argv = resolution.argv
        elif resolution.argv and resolution.argv[0] == "__helper__":
            return ToolResult(
                command=" ".join(spec.argv),
                ok=False,
                stdout="",
                stderr="",
                exit_code=1,
                error="helper daemon requested but not implemented in demo runner",
                tool_name=tool_name,
                privilege_note=privilege_note,
            )
    elif spec.privilege == "root":
        privilege_note = (
            "Fixture runner: executing base argv without live privilege elevation."
        )

    result = run_allowlisted(argv, runner=runner, tool_name=tool_name)
    result.privilege_note = privilege_note
    # Normalize command key for fixture runners that key on the base argv
    # (without sudo prefix).
    if result.ok and argv[:1] == ["sudo"]:
        result.command = " ".join(spec.argv)
    return result
