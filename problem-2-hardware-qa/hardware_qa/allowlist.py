from __future__ import annotations

import shlex
from dataclasses import dataclass


class AllowlistError(ValueError):
    """Raised when a command is not on the read-only allow-list."""


# Exact binary names that may be invoked. No shells, no pipes, no redirects.
ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        "lscpu",
        "lsblk",
        "free",
        "lspci",
        "lsusb",
        "uname",
        "nproc",
        "hostnamectl",
        "df",
        "cat",
        "dmidecode",
    }
)

# Safe absolute paths readable via `cat` only.
ALLOWED_CAT_PATHS: frozenset[str] = frozenset(
    {
        "/proc/cpuinfo",
        "/proc/meminfo",
        "/proc/version",
        "/proc/uptime",
        "/sys/class/dmi/id/product_name",
        "/sys/class/dmi/id/board_name",
        "/sys/class/dmi/id/sys_vendor",
        "/sys/class/dmi/id/bios_version",
        "/sys/class/dmi/id/product_version",
    }
)

# Allowed flags per binary. Unknown flags are rejected.
ALLOWED_FLAGS: dict[str, frozenset[str]] = {
    "lscpu": frozenset(),
    "lsblk": frozenset({"-a", "-b", "-d", "-f", "-j", "-l", "-n", "-o", "-p", "-t", "-P"}),
    "free": frozenset({"-b", "-h", "-k", "-m", "-g", "-t", "-s", "-c"}),
    "lspci": frozenset({"-v", "-nn", "-k", "-mm"}),
    "lsusb": frozenset({"-v", "-t"}),
    "uname": frozenset({"-a", "-r", "-m", "-s", "-n", "-v"}),
    "nproc": frozenset({"-a"}),
    "hostnamectl": frozenset(),
    "df": frozenset({"-h", "-T", "-B"}),
    "cat": frozenset(),
    "dmidecode": frozenset({"-t", "-s"}),
}

# dmidecode -t types that are informational (still may need root).
ALLOWED_DMIDECODE_TYPES: frozenset[str] = frozenset(
    {
        "bios",
        "system",
        "baseboard",
        "chassis",
        "processor",
        "memory",
        "cache",
        "connector",
        "slot",
        "0",
        "1",
        "2",
        "3",
        "4",
        "16",
        "17",
        "19",
    }
)

# Characters / tokens that must never appear (shell metacharacters).
_FORBIDDEN_TOKENS = frozenset(
    {
        "|",
        "||",
        "&",
        "&&",
        ";",
        ">",
        ">>",
        "<",
        "<<",
        "$(",
        "`",
        "\n",
        "\r",
    }
)


@dataclass(frozen=True)
class ValidatedCommand:
    binary: str
    argv: list[str]


def is_allowed(command: str | list[str]) -> bool:
    try:
        validate_command(command)
        return True
    except AllowlistError:
        return False


def validate_command(command: str | list[str]) -> ValidatedCommand:
    """
    Parse and validate a command against the read-only allow-list.

    Accepts a string (shell-like but without shell execution) or an argv list.
    Rejects pipes, redirects, absolute binary paths outside PATH basename, and
    any cat target outside ALLOWED_CAT_PATHS.
    """
    if isinstance(command, str):
        text = command.strip()
        if not text:
            raise AllowlistError("empty command")
        for bad in _FORBIDDEN_TOKENS:
            if bad in text:
                raise AllowlistError(f"forbidden shell token: {bad!r}")
        try:
            argv = shlex.split(text)
        except ValueError as exc:
            raise AllowlistError(f"cannot parse command: {exc}") from exc
    else:
        argv = list(command)
        if not argv:
            raise AllowlistError("empty command")
        joined = " ".join(argv)
        for bad in _FORBIDDEN_TOKENS:
            if bad in joined:
                raise AllowlistError(f"forbidden shell token: {bad!r}")

    binary = argv[0]
    if "/" in binary:
        raise AllowlistError("absolute/relative binary paths are not allowed; use basename only")
    if binary not in ALLOWED_BINARIES:
        raise AllowlistError(f"binary not allow-listed: {binary}")

    allowed_flags = ALLOWED_FLAGS[binary]
    args = argv[1:]

    if binary == "cat":
        if not args or len(args) != 1:
            raise AllowlistError("cat requires exactly one allow-listed path")
        path = args[0]
        if path not in ALLOWED_CAT_PATHS:
            raise AllowlistError(f"cat path not allow-listed: {path}")
        return ValidatedCommand(binary=binary, argv=argv)

    if binary == "dmidecode":
        _validate_dmidecode(args)
        return ValidatedCommand(binary=binary, argv=argv)

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            # Support combined short flags like -lh only if each char is allowed as -x
            if arg.startswith("--"):
                raise AllowlistError(f"long flags not allow-listed for {binary}: {arg}")
            # -o NAME takes a value for lsblk
            if arg == "-o":
                if arg not in allowed_flags:
                    raise AllowlistError(f"flag not allow-listed: {arg}")
                if i + 1 >= len(args):
                    raise AllowlistError("lsblk -o requires a column list")
                _validate_lsblk_columns(args[i + 1])
                i += 2
                continue
            if arg == "-t" and binary == "df":
                i += 1
                continue
            if arg == "-B" and binary == "df":
                if i + 1 >= len(args):
                    raise AllowlistError("df -B requires a size argument")
                i += 2
                continue
            if arg == "-s" and binary == "free":
                if i + 1 >= len(args):
                    raise AllowlistError("free -s requires seconds")
                if not args[i + 1].isdigit():
                    raise AllowlistError("free -s must be an integer")
                i += 2
                continue
            if arg == "-c" and binary == "free":
                if i + 1 >= len(args):
                    raise AllowlistError("free -c requires count")
                if not args[i + 1].isdigit():
                    raise AllowlistError("free -c must be an integer")
                i += 2
                continue
            # Single or clustered short flags: -h, -lh style
            if len(arg) > 2 and arg[1] != "-":
                for ch in arg[1:]:
                    flag = f"-{ch}"
                    if flag not in allowed_flags:
                        raise AllowlistError(f"flag not allow-listed: {flag}")
                i += 1
                continue
            if arg not in allowed_flags:
                raise AllowlistError(f"flag not allow-listed: {arg}")
            i += 1
            continue
        # positional args: generally not allowed except known cases
        raise AllowlistError(f"unexpected argument for {binary}: {arg}")

    return ValidatedCommand(binary=binary, argv=argv)


def _validate_lsblk_columns(cols: str) -> None:
    allowed = {
        "NAME",
        "SIZE",
        "TYPE",
        "FSTYPE",
        "MOUNTPOINT",
        "MODEL",
        "ROTA",
        "TRAN",
        "RM",
        "HOTPLUG",
        "SERIAL",
        "UUID",
        "LABEL",
        "PKNAME",
        "KNAME",
    }
    for col in cols.split(","):
        col = col.strip().upper()
        if col and col not in allowed:
            raise AllowlistError(f"lsblk column not allow-listed: {col}")


def _validate_dmidecode(args: list[str]) -> None:
    allowed_flags = ALLOWED_FLAGS["dmidecode"]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg not in allowed_flags:
            raise AllowlistError(f"dmidecode flag not allow-listed: {arg}")
        if arg in {"-t", "-s"}:
            if i + 1 >= len(args):
                raise AllowlistError(f"dmidecode {arg} requires a value")
            value = args[i + 1]
            if arg == "-t" and value.lower() not in ALLOWED_DMIDECODE_TYPES:
                raise AllowlistError(f"dmidecode type not allow-listed: {value}")
            if arg == "-s" and any(c in value for c in "|;&#`$"):
                raise AllowlistError("invalid dmidecode -s value")
            i += 2
            continue
        i += 1
