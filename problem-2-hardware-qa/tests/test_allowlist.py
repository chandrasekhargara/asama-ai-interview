from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from hardware_qa.allowlist import AllowlistError, is_allowed, validate_command
from hardware_qa.tools import run_allowlisted


def test_allows_safe_read_only_commands():
    for cmd in [
        "lscpu",
        "free -h",
        "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN",
        "cat /proc/meminfo",
        "lspci",
        "uname -a",
        "dmidecode -t memory",
        "df -hT",
    ]:
        assert is_allowed(cmd), cmd
        v = validate_command(cmd)
        assert v.binary == cmd.split()[0]


def test_rejects_shell_metacharacters():
    for cmd in [
        "lscpu | cat",
        "free -h; rm -rf /",
        "cat /proc/meminfo && whoami",
        "uname -a > /tmp/x",
        "lscpu $(whoami)",
        "lscpu `id`",
    ]:
        assert not is_allowed(cmd), cmd
        with pytest.raises(AllowlistError):
            validate_command(cmd)


def test_rejects_unknown_binaries_and_paths():
    for cmd in [
        "rm -rf /",
        "bash",
        "sh -c lscpu",
        "curl http://example.com",
        "python3 -c 'print(1)'",
        "/usr/bin/lscpu",
        "cat /etc/shadow",
        "cat /proc/meminfo /proc/cpuinfo",
        "cat ../../etc/passwd",
    ]:
        assert not is_allowed(cmd), cmd


def test_rejects_disallowed_flags():
    assert not is_allowed("free --si")
    assert not is_allowed("dmidecode -t 99")
    assert not is_allowed("lsblk -o NAME,EVIL")


def test_run_allowlisted_does_not_execute_rejected():
    result = run_allowlisted("cat /etc/passwd")
    assert result.ok is False
    assert result.exit_code == 126
    assert "allow-listed" in (result.error or "")


def test_run_allowlisted_executes_lscpu_when_present():
    result = run_allowlisted("lscpu")
    # In CI/containers lscpu almost always exists
    if result.exit_code == 127:
        pytest.skip("lscpu not installed")
    assert result.ok
    assert "CPU" in result.stdout or "Architecture" in result.stdout or result.stdout
