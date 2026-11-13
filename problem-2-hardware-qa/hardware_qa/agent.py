from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .parsers import (
    parse_dmidecode_memory,
    parse_free,
    parse_lscpu,
    parse_lsblk,
    parse_lspci_gpus,
    parse_meminfo,
)
from .privileges import PrivilegeStrategy
from .tools import (
    INTENT_TOOLS,
    TOOL_REGISTRY,
    ToolResult,
    run_named_tool,
)


@dataclass
class TurnResult:
    question: str
    answer: str
    tools_used: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    structured: dict = field(default_factory=dict)
    mode: str = "deterministic"


class HardwareQAAgent:
    """
    Tool-calling hardware Q&A loop.

    The classifier/LLM selects allow-listed *tool names* only (never raw shell).
    Answers are synthesized strictly from structured JSON derived from tool
    stdout — if a field is missing, we say it is unavailable.
    """

    def __init__(
        self,
        runner=None,
        *,
        privilege_strategy: PrivilegeStrategy | None = None,
    ) -> None:
        self.runner = runner
        self.privilege_strategy = privilege_strategy
        self.history: list[tuple[str, str]] = []
        # Multi-turn context cache (guide: conversation cache for follow-ups).
        self.context_cache: dict[str, Any] = {
            "last_intents": [],
            "last_structured": {},
            "facts": {},
        }

    def ask(self, question: str) -> TurnResult:
        intents = self._classify(question)
        tool_names = self._select_tools(intents)
        tool_results: list[ToolResult] = []
        for name in tool_names:
            tool_results.append(
                run_named_tool(
                    name,
                    runner=self.runner,
                    privilege_strategy=self.privilege_strategy,
                    params=self._params_for(name, question),
                )
            )
            # Strategy C: if root tool failed, run declared fallbacks.
            spec = TOOL_REGISTRY.get(name)
            if spec and not tool_results[-1].ok and spec.fallbacks:
                for fb in spec.fallbacks:
                    if fb not in tool_names:
                        tool_results.append(
                            run_named_tool(
                                fb,
                                runner=self.runner,
                                privilege_strategy=self.privilege_strategy,
                            )
                        )

        structured = self._structure(intents, tool_results)
        self._update_context_cache(intents, structured)

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
            tool_names=[t.tool_name or "" for t in tool_results if t.tool_name],
            structured=structured,
            mode=mode,
        )

    def _params_for(self, tool_name: str, question: str) -> dict:
        if tool_name in {"get_dmi_memory", "get_memory_topology"}:
            return {"include_empty_slots": True}
        return {}

    def _select_tools(self, intents: list[str]) -> list[str]:
        names: list[str] = []
        for intent in intents:
            for name in INTENT_TOOLS.get(intent, []):
                if name not in names:
                    names.append(name)
        return names

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

        # Follow-ups: "and what about the GPU?" — inherit domain from cache/history
        # when the new question has no concrete intent yet, or is a bare follow-up.
        follow_up = bool(re.search(r"\b(what about|how about|and|also)\b", q))
        if follow_up:
            # Explicit entity in the follow-up still wins (GPU/RAM/…).
            if not intents and self.context_cache.get("last_intents"):
                for prev_intent in self.context_cache["last_intents"]:
                    add(prev_intent)
            elif not intents and self.history:
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
            add("system")
            add("cpu")
            add("memory")
            add("storage")
        return intents

    def _update_context_cache(self, intents: list[str], structured: dict) -> None:
        self.context_cache["last_intents"] = list(intents)
        self.context_cache["last_structured"] = structured
        facts = self.context_cache.setdefault("facts", {})
        for key in (
            "memory_free",
            "memory_meminfo",
            "memory_dmi",
            "cpu",
            "storage",
            "gpus",
        ):
            if key in structured and structured[key]:
                facts[key] = structured[key]

    def _structure(self, intents: list[str], results: list[ToolResult]) -> dict:
        by_name = {r.tool_name: r for r in results if r.tool_name}
        by_cmd = {r.command: r for r in results}
        out: dict = {"intents": intents, "errors": [], "tools": []}

        for r in results:
            out["tools"].append(
                {
                    "name": r.tool_name,
                    "command": r.command,
                    "ok": r.ok,
                    "privilege_note": r.privilege_note,
                }
            )
            if not r.ok:
                out["errors"].append(
                    {"tool": r.tool_name, "command": r.command, "error": r.error}
                )

        mem = by_name.get("get_memory_summary") or by_cmd.get("free -b") or by_cmd.get("free -h")
        if mem and mem.ok:
            out["memory_free"] = parse_free(mem.stdout).__dict__

        meminfo = by_name.get("get_meminfo") or by_cmd.get("cat /proc/meminfo")
        if meminfo and meminfo.ok:
            out["memory_meminfo"] = parse_meminfo(meminfo.stdout).__dict__

        cpu = by_name.get("get_cpu_info") or by_cmd.get("lscpu")
        if cpu and cpu.ok:
            out["cpu"] = parse_lscpu(cpu.stdout).__dict__

        blk = by_name.get("get_block_devices")
        if blk and blk.ok:
            devices = parse_lsblk(blk.stdout)
            out["storage"] = [
                d.__dict__ | {"is_nvme": d.is_nvme, "is_ssd": d.is_ssd} for d in devices
            ]
        else:
            # Legacy -P fixture path
            storage_cmd = "lsblk -P -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,FSTYPE,MOUNTPOINT"
            if storage_cmd in by_cmd and by_cmd[storage_cmd].ok:
                devices = parse_lsblk(by_cmd[storage_cmd].stdout)
                out["storage"] = [
                    d.__dict__ | {"is_nvme": d.is_nvme, "is_ssd": d.is_ssd} for d in devices
                ]

        dmi = (
            by_name.get("get_dmi_memory")
            or by_name.get("get_memory_topology")
            or by_cmd.get("dmidecode -t memory")
        )
        if dmi:
            if dmi.ok:
                parsed = parse_dmidecode_memory(dmi.stdout).__dict__
                out["memory_dmi"] = parsed
            else:
                out["memory_dmi"] = {
                    "raw_error": dmi.error or dmi.stderr,
                    "note": (
                        dmi.privilege_note
                        or "dmidecode often needs root; answer limited to free/meminfo"
                    ),
                    "unavailable": True,
                }

        pci = by_name.get("get_pci_devices") or by_cmd.get("lspci")
        if pci and pci.ok:
            out["gpus"] = parse_lspci_gpus(pci.stdout)
            out["pci_sample"] = pci.stdout.splitlines()[:15]

        return out

    def _answer_deterministic(
        self,
        question: str,
        intents: list[str],
        structured: dict,
        results: list[ToolResult],
    ) -> str:
        """Anti-hallucination: only emit facts present in structured JSON."""
        parts: list[str] = []
        q = question.lower()

        if "memory" in intents or "memory_slots" in intents:
            mem = structured.get("memory_free") or structured.get("memory_meminfo") or {}
            total = mem.get("total_human")
            avail = mem.get("available_human")
            dmi = structured.get("memory_dmi") or {}
            upgrade_q = bool(re.search(r"\b(add|upgrade|more|slot|max|maximum)\b", q))
            pdf_style = self._memory_upgrade_summary(dmi, total)
            if upgrade_q and pdf_style:
                parts.append(pdf_style)
            else:
                if total:
                    line = f"This machine currently has about {total} of RAM"
                    if avail:
                        line += f" ({avail} available)"
                    line += "."
                    parts.append(line)
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
                elif dmi.get("unavailable") or dmi.get("raw_error") or dmi.get("note"):
                    parts.append(
                        "DIMM slot / max-capacity details are unavailable "
                        f"({dmi.get('raw_error') or 'dmidecode unavailable'}). "
                        "Re-run with Strategy A scoped sudo for `dmidecode -t memory`, "
                        "or a Strategy B helper daemon."
                    )
                elif not total:
                    parts.append(
                        "RAM size is unavailable — get_memory_summary/get_meminfo "
                        "returned no data."
                    )

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
                parts.append("CPU model is unavailable — get_cpu_info returned no data.")

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
                parts.append(
                    "Storage layout is unavailable — get_block_devices returned no devices."
                )

        if "pci" in intents:
            gpus = structured.get("gpus")
            if gpus is None and "gpus" in self.context_cache.get("facts", {}):
                gpus = self.context_cache["facts"]["gpus"]
            gpus = gpus or []
            if gpus:
                parts.append("GPU / display adapters:\n- " + "\n- ".join(gpus))
            else:
                parts.append(
                    "GPU information is unavailable — no VGA/3D/Display devices "
                    "matched in get_pci_devices output."
                )

        if "system" in intents:
            for r in results:
                if r.tool_name == "get_system_uname" and r.ok:
                    parts.append(f"Kernel: {r.stdout.strip()}.")
                if r.tool_name == "get_system_vendor" and r.ok and r.stdout.strip():
                    parts.append(f"Vendor: {r.stdout.strip()}.")
                if r.tool_name == "get_system_product" and r.ok and r.stdout.strip():
                    parts.append(f"Product: {r.stdout.strip()}.")

        if "disk_space" in intents:
            for r in results:
                if r.tool_name == "get_disk_space" and r.ok:
                    lines = [ln for ln in r.stdout.splitlines() if ln.strip()][:8]
                    parts.append("Filesystem usage (truncated):\n" + "\n".join(lines))

        if not parts:
            errs = structured.get("errors") or []
            if errs:
                return (
                    "I couldn't gather hardware facts. "
                    + "; ".join(e["error"] for e in errs[:3])
                )
            return "I don't know — no relevant tools produced usable structured data."

        return " ".join(parts)

    @staticmethod
    def _parse_capacity_gb(text: str | None) -> float | None:
        if not text:
            return None
        m = re.search(r"([\d.]+)\s*(Gi|GB|G)?", text, re.I)
        if not m:
            return None
        value = float(m.group(1))
        unit = (m.group(2) or "G").lower()
        if unit.startswith("g"):
            return value
        if unit.startswith("m"):
            return value / 1024.0
        return value

    def _memory_upgrade_summary(self, dmi: dict, total_human: str | None) -> str | None:
        """
        Prefer the PDF-style answer when slot + max-capacity facts are present:
        'You have 16 GB in 1 of 2 slots. The board supports up to 64 GB, so you
        can add a stick of up to 32 GB.'
        """
        if dmi.get("unavailable"):
            return None
        slots_total = dmi.get("slots_total")
        slots_used = dmi.get("slots_used")
        max_cap = dmi.get("max_capacity")
        modules = dmi.get("installed_modules") or []
        if slots_total is None or slots_used is None or not max_cap:
            return None

        installed_label = modules[0] if len(modules) == 1 else (
            " + ".join(modules) if modules else total_human
        )
        if not installed_label:
            return None

        installed_gb = self._parse_capacity_gb(
            modules[0] if len(modules) == 1 else total_human or installed_label
        )
        if installed_gb is not None and len(modules) <= 1:
            installed_label = f"{int(installed_gb) if installed_gb.is_integer() else installed_gb} GB"

        max_gb = self._parse_capacity_gb(max_cap)
        parts = [
            f"You have {installed_label} in {slots_used} of {slots_total} slots. "
            f"The board supports up to {max_cap}"
        ]
        empty = slots_total - slots_used
        if empty > 0 and max_gb is not None and installed_gb is not None:
            remaining = max(0.0, max_gb - installed_gb)
            per_slot = max_gb / slots_total if slots_total else remaining
            per_stick = min(remaining, per_slot)
            if per_stick > 0:
                stick = int(per_stick) if float(per_stick).is_integer() else per_stick
                parts.append(f", so you can add a stick of up to {stick} GB")
        parts.append(".")
        parts.append(" Match DDR generation/speed with existing modules.")
        return "".join(parts)

    def _answer_with_llm(
        self,
        question: str,
        structured: dict,
        results: list[ToolResult],
    ) -> str:
        from openai import OpenAI

        prompt = (
            "You are a Linux hardware assistant. Answer ONLY using the structured "
            "JSON facts below. If a field is missing or marked unavailable, say so. "
            "Do not invent RAM slot counts or max capacity. Never propose shell "
            "commands — tools were already selected by name from an allow-list.\n\n"
            f"Question: {question}\n\nStructured JSON:\n{structured}\n"
        )
        client = OpenAI()
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400,
        )
        return (resp.choices[0].message.content or "").strip()
