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
from hardware_qa.privileges import STRATEGY_DOCS, preferred_strategy


def _run_pdf_fixture_demo() -> int:
    """Reproduce the interview PDF example with canned tool output."""
    free_b = """\
               total        used        free      shared  buff/cache   available
Mem:     17179869184  4294967296  8589934592   104857600  4294967296  11811160064
Swap:     4294967296           0  4294967296
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
    lsblk_json = json.dumps(
        {
            "blockdevices": [
                {
                    "name": "nvme0n1",
                    "size": "512G",
                    "type": "disk",
                    "model": "Samsung SSD 990",
                    "rota": 0,
                    "tran": "nvme",
                    "fstype": None,
                    "mountpoint": None,
                }
            ]
        }
    )

    outputs = {
        "free -b": free_b,
        "cat /proc/meminfo": meminfo,
        "dmidecode -t memory": dmidecode,
        "lsblk -J -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT": lsblk_json,
        "lscpu": "Model name: Fixture CPU\nCPU(s): 8\nArchitecture: x86_64\n",
        "nproc": "8\n",
        "lspci": "00:02.0 VGA compatible controller: Fixture GPU\n",
        "uname -a": "Linux fixture 6.1.0\n",
        "cat /sys/class/dmi/id/sys_vendor": "FixtureVendor\n",
        "cat /sys/class/dmi/id/product_name": "FixtureLaptop\n",
    }

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        # Strip sudo -n /abs/path wrappers for fixture lookup.
        cleaned = list(argv)
        if cleaned and cleaned[0] == "sudo":
            # sudo -n /usr/sbin/dmidecode -t memory → dmidecode -t memory
            if len(cleaned) >= 3:
                target = cleaned[2].rsplit("/", 1)[-1]
                cleaned = [target, *cleaned[3:]]
        key = " ".join(cleaned)
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
    print("Uses allow-listed *tool names* with canned output matching the interview PDF.")
    print(f"Privilege strategy: {preferred_strategy().value}")
    upgrade_answer = ""
    follow_up_tools = []
    for q in samples:
        result = agent.ask(q)
        print(f"\nQ: {q}")
        print(f"A: {result.answer}")
        print(f"   tools: {', '.join(result.tool_names)}")
        print(f"   argv:  {', '.join(result.tools_used)}")
        if "add more RAM" in q:
            upgrade_answer = result.answer
        if "GPU" in q:
            follow_up_tools = result.tool_names

    assert "1 of 2 slots" in upgrade_answer
    assert "64 GB" in upgrade_answer
    assert "32 GB" in upgrade_answer
    assert "get_pci_devices" in follow_up_tools
    print("\nPDF example assertions passed (incl. GPU follow-up via context cache).")
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
    parser.add_argument(
        "--privileges",
        action="store_true",
        help="Print privilege strategies A/B/C and exit.",
    )
    args = parser.parse_args(argv)

    if args.privileges:
        print("Hardware Q&A privilege strategies:\n")
        for strat, doc in STRATEGY_DOCS.items():
            print(f"  {strat.value}: {doc}")
        print(f"\nActive (HARDWARE_QA_PRIVILEGE / auto): {preferred_strategy().value}")
        return 0

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
        print(f"Privilege strategy: {preferred_strategy().value}")
        for q in samples:
            result = agent.ask(q)
            print(f"\nQ: {q}")
            print(f"A: {result.answer}")
            print(f"   tools: {', '.join(result.tool_names)}")
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
                        "tool_names": result.tool_names,
                        "structured": result.structured,
                        "mode": result.mode,
                    },
                    indent=2,
                )
            )
        else:
            print(result.answer)
        return 0

    print("Hardware Q&A (tool-name allow-list; never raw shell). Type 'exit' to quit.")
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
