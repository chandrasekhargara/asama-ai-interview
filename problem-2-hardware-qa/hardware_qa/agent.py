from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .parsers import (
    parse_dmidecode_memory,
    parse_free_h,
    parse_lscpu,
    parse_lsblk,
    parse_lspci_gpus,
    parse_meminfo,
)
from .tools import TOOL_CATALOG, ToolResult, run_allowlisted


@dataclass
class TurnResult:
    question: str
    answer: str
    tools_used: list[str] = field(default_factory=list)
    structured: dict = field(default_factory=dict)
    mode: str = "deterministic"


class HardwareQAAgent:
    """
    Tool-calling hardware Q&A loop.

    Without OPENAI_API_KEY: intent → allow-listed commands → parsers → answer.
    With OPENAI_API_KEY: same tools, LLM phrases the final answer from tool output only.
    """

    def __init__(self, runner=None) -> None:
        self.runner = runner
        self.history: list[tuple[str, str]] = []

    def ask(self, question: str) -> TurnResult:
        intents = self._classify(question)
        tool_results: list[ToolResult] = []
        for intent in intents:
            for cmd in TOOL_CATALOG.get(intent, {}).get("commands", []):
                tool_results.append(run_allowlisted(cmd, runner=self.runner))

        structured = self._structure(intents, tool_results)
        if os.environ.get("OPENAI_API_KEY"):
            answer = self._answer_with_llm(question, structured, tool_results)
            mode = "openai"
        else:
            answer = self._answer_deterministic(question, intents, structured, tool_results)
            mode = "deterministic"

        self.history.append((question, answer))
        return TurnResult(
            question=question,
            answer=answer,
            tools_used=[t.command for t in tool_results],
            structured=structured,
            mode=mode,
        )

    def _classify(self, question: str) -> list[str]:
        q = question.lower()
        intents: list[str] = []

        def add(name: str) -> None:
            if name not in intents:
                intents.append(name)

        if re.search(r"\b(ram|memory|mem|dimm|slot)\b", q):
            add("memory")
            if re.search(r"\b(add|upgrade|slot|max|maximum|more)\b", q):
                add("memory_slots")
        if re.search(r"\b(cpu|processor|core|cores|thread)\b", q):
            add("cpu")
        if re.search(r"\b(ssd|hdd|nvme|disk|drive|storage|lsblk)\b", q):
            add("storage")
        if re.search(r"\b(gpu|graphics|vga|display|pci)\b", q):
            add("pci")
        if re.search(r"\b(disk space|filesystem|df\b|free space)\b", q):
            add("disk_space")
        if re.search(r"\b(hostname|kernel|uname|vendor|model|laptop|system)\b", q):
            add("system")
        # Follow-ups like "and what about the GPU?" already match their own intents above.
        # Only inherit prior domain when the new question has no concrete intent yet.

        if not intents:
            if self.history and re.search(r"\b(what about|and|also)\b", q):
                prev = self.history[-1][0].lower()
                if re.search(r"\b(gpu|graphics)\b", prev):
                    add("pci")
                elif re.search(r"\b(ram|memory)\b", prev):
                    add("memory")
                elif re.search(r"\b(cpu|processor)\b", prev):
                    add("cpu")
                elif re.search(r"\b(ssd|disk|storage|nvme)\b", prev):
                    add("storage")
        if not intents:
            # Broad default for vague hardware questions
            add("system")
            add("cpu")
            add("memory")
            add("storage")
        return intents

    def _structure(self, intents: list[str], results: list[ToolResult]) -> dict:
        by_cmd = {r.command: r for r in results}
        out: dict = {"intents": intents, "errors": []}

        for r in results:
            if not r.ok:
                out["errors"].append({"command": r.command, "error": r.error})

        if "free -h" in by_cmd and by_cmd["free -h"].ok:
            out["memory_free"] = parse_free_h(by_cmd["free -h"].stdout).__dict__
        if "cat /proc/meminfo" in by_cmd and by_cmd["cat /proc/meminfo"].ok:
            out["memory_meminfo"] = parse_meminfo(by_cmd["cat /proc/meminfo"].stdout).__dict__
        if "lscpu" in by_cmd and by_cmd["lscpu"].ok:
            out["cpu"] = parse_lscpu(by_cmd["lscpu"].stdout).__dict__
        storage_cmd = "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT"
        if storage_cmd in by_cmd and by_cmd[storage_cmd].ok:
            devices = parse_lsblk(by_cmd[storage_cmd].stdout)
            out["storage"] = [d.__dict__ | {"is_nvme": d.is_nvme, "is_ssd": d.is_ssd} for d in devices]
        if "dmidecode -t memory" in by_cmd:
            r = by_cmd["dmidecode -t memory"]
            if r.ok:
                out["memory_dmi"] = parse_dmidecode_memory(r.stdout).__dict__
            else:
                out["memory_dmi"] = {
                    "raw_error": r.error or r.stderr,
                    "note": "dmidecode often needs root; answer limited to free/meminfo",
                }
        if "lspci" in by_cmd and by_cmd["lspci"].ok:
            out["gpus"] = parse_lspci_gpus(by_cmd["lspci"].stdout)
            out["pci_sample"] = by_cmd["lspci"].stdout.splitlines()[:15]
        return out

    def _answer_deterministic(
        self,
        question: str,
        intents: list[str],
        structured: dict,
        results: list[ToolResult],
    ) -> str:
        parts: list[str] = []
        q = question.lower()

        if "memory" in intents or "memory_slots" in intents:
            mem = structured.get("memory_free") or structured.get("memory_meminfo") or {}
            total = mem.get("total_human")
            avail = mem.get("available_human")
            if total:
                line = f"This machine currently has about {total} of RAM"
                if avail:
                    line += f" ({avail} available)"
                line += "."
                parts.append(line)
            dmi = structured.get("memory_dmi") or {}
            if dmi.get("max_capacity") or dmi.get("slots_total") is not None:
                slots_total = dmi.get("slots_total")
                slots_used = dmi.get("slots_used")
                max_cap = dmi.get("max_capacity")
                modules = dmi.get("installed_modules") or []
                detail = []
                if slots_total is not None and slots_used is not None:
                    detail.append(f"{slots_used} of {slots_total} slots filled")
                if modules:
                    detail.append("installed: " + ", ".join(modules))
                if max_cap:
                    detail.append(f"board max capacity {max_cap}")
                if detail:
                    parts.append("From DMI: " + "; ".join(detail) + ".")
                if (
                    max_cap
                    and slots_total
                    and slots_used is not None
                    and slots_used < slots_total
                    and re.search(r"add|upgrade|more", q)
                ):
                    parts.append(
                        f"You can likely add more RAM in the empty slot(s), "
                        f"up to the board maximum of {max_cap}. "
                        "Match DDR generation/speed with existing modules."
                    )
            elif dmi.get("raw_error") or dmi.get("note"):
                parts.append(
                    "I could not read DIMM slot / max-capacity details "
                    f"({dmi.get('raw_error') or 'dmidecode unavailable'}). "
                    "Re-run with permissions for `dmidecode -t memory` for upgrade advice."
                )
            elif not total:
                parts.append("I don't know the RAM size — `free`/`meminfo` returned no data.")

        if "cpu" in intents:
            cpu = structured.get("cpu") or {}
            if cpu.get("model"):
                bits = [cpu["model"]]
                if cpu.get("cpus"):
                    bits.append(f"{cpu['cpus']} logical CPUs")
                if cpu.get("architecture"):
                    bits.append(cpu["architecture"])
                parts.append("CPU: " + ", ".join(bits) + ".")
            else:
                parts.append("I don't know the CPU model — `lscpu` failed or was empty.")

        if "storage" in intents:
            devices = structured.get("storage") or []
            disks = [d for d in devices if d.get("type") == "disk"] or devices
            if disks:
                desc = []
                for d in disks[:6]:
                    kind = "NVMe SSD" if d.get("is_nvme") else ("SSD" if d.get("is_ssd") else "disk")
                    piece = f"{d.get('name')} ({kind}"
                    if d.get("size"):
                        piece += f", {d['size']}"
                    if d.get("model"):
                        piece += f", {d['model']}"
                    piece += ")"
                    desc.append(piece)
                parts.append("Storage: " + "; ".join(desc) + ".")
                if re.search(r"nvme", q):
                    if any(d.get("is_nvme") for d in disks):
                        parts.append("Yes — at least one NVMe device is present.")
                    else:
                        parts.append("I do not see an NVMe transport on the listed disks.")
            else:
                parts.append("I don't know the storage layout — `lsblk` returned no devices.")

        if "pci" in intents:
            gpus = structured.get("gpus") or []
            if gpus:
                parts.append("GPU / display adapters:\n- " + "\n- ".join(gpus))
            else:
                parts.append(
                    "No VGA/3D/Display devices matched in `lspci` output "
                    "(or lspci failed)."
                )

        if "system" in intents:
            # Pull raw uname / vendor if present
            for r in results:
                if r.command == "uname -a" and r.ok:
                    parts.append(f"Kernel: {r.stdout.strip()}.")
                if r.command.endswith("sys_vendor") and r.ok and r.stdout.strip():
                    parts.append(f"Vendor: {r.stdout.strip()}.")
                if r.command.endswith("product_name") and r.ok and r.stdout.strip():
                    parts.append(f"Product: {r.stdout.strip()}.")

        if "disk_space" in intents:
            for r in results:
                if r.command.startswith("df") and r.ok:
                    lines = [ln for ln in r.stdout.splitlines() if ln.strip()][:8]
                    parts.append("Filesystem usage (truncated):\n" + "\n".join(lines))

        if not parts:
            errs = structured.get("errors") or []
            if errs:
                return (
                    "I couldn't gather hardware facts. "
                    + "; ".join(e["error"] for e in errs[:3])
                )
            return "I don't know — no relevant tools produced usable data."

        # Safety: never invent upgrade numbers beyond tool output
        return " ".join(parts)

    def _answer_with_llm(
        self,
        question: str,
        structured: dict,
        results: list[ToolResult],
    ) -> str:
        from openai import OpenAI

        tool_blob = "\n\n".join(
            f"$ {r.command}\nexit={r.exit_code}\n{r.stdout or r.error or ''}"[:4000]
            for r in results
        )
        prompt = (
            "You are a Linux hardware assistant. Answer ONLY using the tool outputs "
            "below. If data is missing, say you don't know. Do not invent RAM slot "
            "counts or max capacity.\n\n"
            f"Question: {question}\n\nTool outputs:\n{tool_blob}\n\n"
            f"Structured: {structured}\n"
        )
        client = OpenAI()
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400,
        )
        return (resp.choices[0].message.content or "").strip()
