from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from hardware_qa.allowlist import AllowlistError, is_allowed, validate_command
from hardware_qa.tools import list_tool_names, run_allowlisted, run_named_tool


def test_allows_safe_read_only_commands():
    for cmd in [
        "lscpu",
        "free -b",
        "free -h",
        "lsblk -J -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN",
        "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN",
        "cat /proc/meminfo",
        "lspci",
        "uname -a",
        "dmidecode -t memory",
        "sudo -n dmidecode -t memory",
        "sudo -n /usr/sbin/dmidecode -t memory",
        "df -hT",
    ]:
        assert is_allowed(cmd), cmd
        v = validate_command(cmd)
        assert v.binary in {cmd.split()[0], "sudo"}


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
        "sudo -n rm -rf /",
        "sudo dmidecode -t memory",  # missing -n
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
    if result.exit_code == 127:
        pytest.skip("lscpu not installed")
    assert result.ok
    assert "CPU" in result.stdout or "Architecture" in result.stdout or result.stdout


def test_named_tools_are_allow_listed():
    names = list_tool_names()
    assert "get_cpu_info" in names
    assert "get_dmi_memory" in names
    assert "get_block_devices" in names
    assert "get_memory_summary" in names
    # Unknown tool name never executes
    bad = run_named_tool("rm_rf_root")
    assert bad.ok is False
    assert bad.exit_code == 126
