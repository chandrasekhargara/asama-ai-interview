#!/usr/bin/env python3
"""Interactive / one-shot CLI for the hardware Q&A assistant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import subprocess

from hardware_qa.agent import HardwareQAAgent


def _run_pdf_fixture_demo() -> int:
    """Reproduce the interview PDF example with canned tool output."""
    free_h = """\
               total        used        free      shared  buff/cache   available
Mem:            16Gi       4.0Gi       8.0Gi       100Mi       4.0Gi        11Gi
Swap:          4.0Gi          0B       4.0Gi
"""
    meminfo = """\
MemTotal:       16777216 kB
MemAvailable:   11534336 kB
"""
    dmidecode = """\
Physical Memory Array
        Maximum Capacity: 64 GB
        Number Of Devices: 2

Memory Device
        Size: 16 GB
        Speed: 3200 MT/s

Memory Device
        Size: No Module Installed
"""
    lsblk = """\
NAME="nvme0n1" SIZE="512G" TYPE="disk" MODEL="Samsung SSD 990" ROTA="0" TRAN="nvme" FSTYPE="" MOUNTPOINT=""
"""

    outputs = {
        "free -h": free_h,
        "cat /proc/meminfo": meminfo,
        "dmidecode -t memory": dmidecode,
        "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT": lsblk,
        "lscpu": "Model name: Fixture CPU\nCPU(s): 8\nArchitecture: x86_64\n",
        "nproc": "8\n",
        "cat /proc/cpuinfo": "processor\t: 0\nmodel name\t: Fixture CPU\n",
        "lspci": "00:02.0 VGA compatible controller: Fixture GPU\n",
        "uname -a": "Linux fixture 6.1.0\n",
        "cat /sys/class/dmi/id/sys_vendor": "FixtureVendor\n",
        "cat /sys/class/dmi/id/product_name": "FixtureLaptop\n",
    }

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        key = " ".join(argv)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, outputs[key], "")
        return subprocess.CompletedProcess(argv, 1, "", f"missing fixture for {key}")

    agent = HardwareQAAgent(runner=runner)
    samples = [
        "How much RAM do I have?",
        "Is my SSD NVMe?",
        "Can I add more RAM, and how much?",
        "And what about the GPU?",
    ]
    print("=== Problem 2 demo: PDF example (fixture tools) ===\n")
    print("Uses allow-listed commands with canned output matching the interview PDF.")
    upgrade_answer = ""
    for q in samples:
        result = agent.ask(q)
        print(f"\nQ: {q}")
        print(f"A: {result.answer}")
        print(f"   tools: {', '.join(result.tools_used)}")
        if "add more RAM" in q:
            upgrade_answer = result.answer

    assert "1 of 2 slots" in upgrade_answer
    assert "64 GB" in upgrade_answer
    assert "32 GB" in upgrade_answer
    print("\nPDF example assertions passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask natural-language questions about this Linux machine's hardware."
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Optional one-shot question. If omitted, starts a REPL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable TurnResult JSON.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a few sample questions against this machine (live tools).",
    )
    parser.add_argument(
        "--demo-pdf",
        action="store_true",
        help="Run the PDF RAM-upgrade example with fixture tool output (no root needed).",
    )
    args = parser.parse_args(argv)

    if args.demo_pdf:
        return _run_pdf_fixture_demo()

    agent = HardwareQAAgent()

    if args.demo:
        samples = [
            "How much RAM do I have?",
            "Is my SSD NVMe?",
            "What CPU is in this machine?",
            "Can I add more RAM, and how much?",
            "And what about the GPU?",
        ]
        print("=== Problem 2 demo: live hardware Q&A (this machine) ===")
        for q in samples:
            result = agent.ask(q)
            print(f"\nQ: {q}")
            print(f"A: {result.answer}")
            print(f"   tools: {', '.join(result.tools_used)}")
        return 0

    if args.question:
        q = " ".join(args.question)
        result = agent.ask(q)
        if args.json:
            print(
                json.dumps(
                    {
                        "question": result.question,
                        "answer": result.answer,
                        "tools_used": result.tools_used,
                        "structured": result.structured,
                        "mode": result.mode,
                    },
                    indent=2,
                )
            )
        else:
            print(result.answer)
        return 0

    print("Hardware Q&A (read-only allow-listed tools). Type 'exit' to quit.")
    print("Set OPENAI_API_KEY for LLM phrasing; otherwise deterministic answers.\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", ":q"}:
            break
        result = agent.ask(q)
        print(f"assistant> {result.answer}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
