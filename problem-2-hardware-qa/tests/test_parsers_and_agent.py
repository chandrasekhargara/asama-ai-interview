from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hardware_qa.agent import HardwareQAAgent
from hardware_qa.parsers import (
    parse_dmidecode_memory,
    parse_free,
    parse_free_h,
    parse_lscpu,
    parse_lsblk,
    parse_meminfo,
)


FREE_H = """\
               total        used        free      shared  buff/cache   available
Mem:            15Gi       4.2Gi       8.1Gi       100Mi       3.0Gi        10Gi
Swap:          4.0Gi          0B       4.0Gi
"""

FREE_B = """\
               total        used        free      shared  buff/cache   available
Mem:     16106127360  4509715660  8697307136   104857600  3221225472  10737418240
Swap:     4294967296           0  4294967296
"""

MEMINFO = """\
MemTotal:       16384000 kB
MemFree:         8192000 kB
MemAvailable:   10485760 kB
"""

LSCPU = """\
Architecture:                            x86_64
CPU(s):                                  8
Thread(s) per core:                      2
Core(s) per socket:                      4
Socket(s):                               1
Model name:                              Test CPU 3.2GHz
"""

LSBLK_JSON = json.dumps(
    {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "size": "512G",
                "type": "disk",
                "model": "Samsung SSD 990",
                "rota": 0,
                "tran": "nvme",
            },
            {
                "name": "sda",
                "size": "1T",
                "type": "disk",
                "model": "ST1000",
                "rota": 1,
                "tran": "sata",
            },
        ]
    }
)

DMIDECODE = """\
Physical Memory Array
        Maximum Capacity: 64 GB
        Number Of Devices: 2

Memory Device
        Size: 16 GB
        Speed: 3200 MT/s

Memory Device
        Size: No Module Installed
"""


def test_parse_memory_helpers():
    h = parse_free_h(FREE_H)
    assert h.total_human == "15Gi"
    assert h.available_human == "10Gi"
    b = parse_free(FREE_B)
    assert b.total_human.endswith("Gi")
    assert b.total_kib is not None
    m = parse_meminfo(MEMINFO)
    assert m.total_kib == 16384000
    assert m.total_human.endswith("Gi")


def test_parse_cpu_and_storage():
    cpu = parse_lscpu(LSCPU)
    assert cpu.model.startswith("Test CPU")
    assert cpu.cpus == 8
    disks = parse_lsblk(LSBLK_JSON)
    assert disks[0].is_nvme and disks[0].is_ssd
    assert disks[1].is_ssd is False


def test_parse_dmidecode_slots():
    s = parse_dmidecode_memory(DMIDECODE)
    assert s.max_capacity == "64 GB"
    assert s.slots_total == 2
    assert s.slots_used == 1
    assert s.installed_modules == ["16 GB"]


def _fake_runner(outputs: dict[str, str]):
    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        cleaned = list(argv)
        if cleaned and cleaned[0] == "sudo" and len(cleaned) >= 3:
            cleaned = [cleaned[2].rsplit("/", 1)[-1], *cleaned[3:]]
        key = " ".join(cleaned)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, outputs[key], "")
        return subprocess.CompletedProcess(argv, 1, "", f"missing fixture for {key}")

    return runner


def test_agent_ram_question_with_fixtures():
    """PDF example: 16 GB in 1 of 2 slots, max 64 GB → can add up to 32 GB."""
    outputs = {
        "free -b": FREE_B,
        "cat /proc/meminfo": MEMINFO,
        "dmidecode -t memory": DMIDECODE,
    }
    agent = HardwareQAAgent(runner=_fake_runner(outputs))
    result = agent.ask("Can I add more RAM, and how much?")
    assert "16 GB" in result.answer
    assert "1 of 2 slots" in result.answer
    assert "64 GB" in result.answer
    assert "32 GB" in result.answer
    assert result.mode == "deterministic"
    assert "get_dmi_memory" in result.tool_names
    assert "get_memory_summary" in result.tool_names or "get_meminfo" in result.tool_names


def test_agent_nvme_question():
    outputs = {
        "lsblk -J -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT": LSBLK_JSON,
    }
    agent = HardwareQAAgent(runner=_fake_runner(outputs))
    result = agent.ask("Is my SSD NVMe?")
    assert "NVMe" in result.answer or "nvme" in result.answer.lower()
    assert "get_block_devices" in result.tool_names


def test_follow_up_gpu_uses_context_cache():
    outputs = {
        "free -b": FREE_B,
        "cat /proc/meminfo": MEMINFO,
        "dmidecode -t memory": DMIDECODE,
        "lspci": "01:00.0 VGA compatible controller: ACME GPU\n",
    }
    agent = HardwareQAAgent(runner=_fake_runner(outputs))
    agent.ask("Can I add more RAM, and how much?")
    follow = agent.ask("And what about the GPU?")
    assert "get_pci_devices" in follow.tool_names
    assert "ACME GPU" in follow.answer
    assert agent.context_cache["last_intents"] == ["pci"]


def test_anti_hallucination_when_dmi_missing():
    outputs = {
        "free -b": FREE_B,
        "cat /proc/meminfo": MEMINFO,
        # dmidecode intentionally missing → runner returns error
    }
    agent = HardwareQAAgent(runner=_fake_runner(outputs))
    result = agent.ask("Can I add more RAM, and how much?")
    assert "unavailable" in result.answer.lower() or "could not" in result.answer.lower() or "Re-run" in result.answer
    assert "32 GB" not in result.answer  # must not invent upgrade size
