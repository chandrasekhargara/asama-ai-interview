from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MemoryInfo:
    total_human: str | None = None
    used_human: str | None = None
    free_human: str | None = None
    available_human: str | None = None
    total_kib: int | None = None


@dataclass
class CpuInfo:
    model: str | None = None
    architecture: str | None = None
    cpus: int | None = None
    threads_per_core: int | None = None
    cores_per_socket: int | None = None
    sockets: int | None = None


@dataclass
class BlockDevice:
    name: str
    size: str | None = None
    type: str | None = None
    model: str | None = None
    rota: str | None = None  # 0 = SSD-like, 1 = rotational
    tran: str | None = None  # nvme, sata, ...
    fstype: str | None = None
    mountpoint: str | None = None

    @property
    def is_nvme(self) -> bool:
        return (self.tran or "").lower() == "nvme" or self.name.startswith("nvme")

    @property
    def is_ssd(self) -> bool:
        if self.is_nvme:
            return True
        if self.rota is not None:
            return self.rota.strip() == "0"
        return False


@dataclass
class DmiMemorySummary:
    max_capacity: str | None = None
    slots_total: int | None = None
    slots_used: int | None = None
    installed_modules: list[str] = field(default_factory=list)
    raw_error: str | None = None


def parse_free_h(text: str) -> MemoryInfo:
    info = MemoryInfo()
    for line in text.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            # Mem: total used free shared buff/cache available
            if len(parts) >= 4:
                info.total_human = parts[1]
                info.used_human = parts[2]
                info.free_human = parts[3]
            if len(parts) >= 7:
                info.available_human = parts[6]
            break
    return info


def parse_meminfo(text: str) -> MemoryInfo:
    info = MemoryInfo()
    kib: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            kib[m.group(1)] = int(m.group(2))
    if "MemTotal" in kib:
        info.total_kib = kib["MemTotal"]
        gb = kib["MemTotal"] / (1024 * 1024)
        info.total_human = f"{gb:.1f}Gi" if gb >= 1 else f"{kib['MemTotal'] // 1024}Mi"
    if "MemAvailable" in kib:
        gb = kib["MemAvailable"] / (1024 * 1024)
        info.available_human = f"{gb:.1f}Gi"
    if "MemFree" in kib:
        gb = kib["MemFree"] / (1024 * 1024)
        info.free_human = f"{gb:.1f}Gi"
    return info


def parse_lscpu(text: str) -> CpuInfo:
    info = CpuInfo()
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip().lower()] = v.strip()
    info.model = kv.get("model name")
    info.architecture = kv.get("architecture")
    for key, attr in [
        ("cpu(s)", "cpus"),
        ("thread(s) per core", "threads_per_core"),
        ("core(s) per socket", "cores_per_socket"),
        ("socket(s)", "sockets"),
    ]:
        if key in kv and kv[key].isdigit():
            setattr(info, attr, int(kv[key]))
    return info


def parse_lsblk(text: str) -> list[BlockDevice]:
    """Parse `lsblk -P` key=value rows, with a whitespace-table fallback."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    if "NAME=" in lines[0]:
        devices: list[BlockDevice] = []
        for line in lines:
            fields = dict(re.findall(r'([A-Z_]+)="([^"]*)"', line))
            if not fields.get("NAME"):
                continue
            devices.append(
                BlockDevice(
                    name=fields.get("NAME", ""),
                    size=fields.get("SIZE") or None,
                    type=fields.get("TYPE") or None,
                    model=fields.get("MODEL") or None,
                    rota=fields.get("ROTA") or None,
                    tran=fields.get("TRAN") or None,
                    fstype=fields.get("FSTYPE") or None,
                    mountpoint=fields.get("MOUNTPOINT") or None,
                )
            )
        return devices

    header = re.split(r"\s+", lines[0].strip())
    cols = [h.upper() for h in header]
    devices = []
    for line in lines[1:]:
        cleaned = re.sub(r"[├─└│]`?-?", "", line).strip()
        parts = re.split(r"\s+", cleaned)
        if not parts:
            continue
        row = {cols[i]: parts[i] if i < len(parts) else None for i in range(len(cols))}
        name = re.sub(r"[^a-zA-Z0-9\-_/]", "", row.get("NAME") or parts[0])
        devices.append(
            BlockDevice(
                name=name,
                size=row.get("SIZE"),
                type=row.get("TYPE"),
                model=row.get("MODEL"),
                rota=row.get("ROTA"),
                tran=row.get("TRAN"),
                fstype=row.get("FSTYPE"),
                mountpoint=row.get("MOUNTPOINT"),
            )
        )
    return devices


def parse_dmidecode_memory(text: str) -> DmiMemorySummary:
    summary = DmiMemorySummary()
    if not text.strip():
        summary.raw_error = "empty dmidecode output"
        return summary

    # Maximum Capacity: 64 GB
    m = re.search(r"Maximum Capacity:\s*(.+)", text, re.I)
    if m:
        summary.max_capacity = m.group(1).strip()

    # Number Of Devices: 2
    m = re.search(r"Number Of Devices:\s*(\d+)", text, re.I)
    if m:
        summary.slots_total = int(m.group(1))

    modules = []
    for block in re.split(r"\nMemory Device\n", text):
        if "Size:" not in block:
            continue
        size_m = re.search(r"^\s*Size:\s*(.+)$", block, re.M)
        if not size_m:
            continue
        size = size_m.group(1).strip()
        if size.lower() in {"no module installed", "not installed", "0"}:
            continue
        modules.append(size)
    summary.installed_modules = modules
    summary.slots_used = len(modules)
    if summary.slots_total is None and modules:
        # Fallback: count Memory Device sections
        summary.slots_total = len(re.findall(r"Memory Device", text))
    return summary


def parse_lspci_gpus(text: str) -> list[str]:
    gpus = []
    for line in text.splitlines():
        if re.search(r"VGA|3D|Display", line, re.I):
            gpus.append(line.strip())
    return gpus
