#!/usr/bin/env python3
"""Interactive / one-shot CLI for the hardware Q&A assistant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hardware_qa.agent import HardwareQAAgent


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
        help="Run a few sample questions non-interactively.",
    )
    args = parser.parse_args(argv)
    agent = HardwareQAAgent()

    if args.demo:
        samples = [
            "How much RAM do I have?",
            "Is my SSD NVMe?",
            "What CPU is in this machine?",
            "Can I add more RAM, and how much?",
            "And what about the GPU?",
        ]
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
