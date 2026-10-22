"""Detección de hardware y sistema. Solo lectura: no modifica nada."""

from __future__ import annotations

import winreg
from dataclasses import asdict, dataclass, field

import psutil

from optiwin.core.power_status import PowerStatus, active_power_scheme, read_power_status
from optiwin.core.winutil import as_list, powershell_json

# Tipos de chasis SMBIOS que corresponden a equipos portátiles.
# 8 Portable, 9 Laptop, 10 Notebook, 11 Handheld, 14 Sub Notebook,
# 30 Tablet, 31 Convertible, 32 Detachable
PORTABLE_CHASSIS = {8, 9, 10, 11, 14, 30, 31, 32}

_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
[pscustomobject]@{
  cpu   = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed)
  gpu   = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM,PNPDeviceID)
  chassis = @((Get-CimInstance Win32_SystemEnclosure).ChassisTypes)
  system = (Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model)
  disks = @(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size)
  ram   = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed)
  batt_full   = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity | Select-Object FullChargedCapacity)
  batt_static = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData | Select-Object DesignedCapacity)
  batt_cycles = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount | Select-Object CycleCount)
} | ConvertTo-Json -Depth 4 -Compress
"""


@dataclass
class CpuInfo:
    name: str
    cores: int
    threads: int
    max_mhz: int


@dataclass
class GpuInfo:
    name: str
    driver: str
    vram_gb: float | None
    kind: str  # "dedicada" | "integrada" | "desconocida"


@dataclass
class DiskInfo:
    name: str
    kind: str  # SSD / HDD / NVMe...
    size_gb: float


@dataclass
class BatteryInfo:
    design_mwh: int | None
    full_mwh: int | None
    cycles: int | None

    @property
    def health_percent(self) -> float | None:
        if self.design_mwh and self.full_mwh:
            return round(100 * self.full_mwh / self.design_mwh, 1)
        return None


@dataclass
class SystemInfo:
    manufacturer: str
    model: str
    is_laptop: bool
    laptop_reason: str
    windows: str
    cpu: CpuInfo | None
    gpus: list[GpuInfo] = field(default_factory=list)
    ram_gb: float = 0.0
    ram_speed_mhz: int | None = None
    disks: list[DiskInfo] = field(default_factory=list)
    battery: BatteryInfo | None = None
    power: PowerStatus | None = None
    power_scheme: tuple[str, str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- Lógica pura (testeable sin Windows real) --------------------------------

def classify_laptop(chassis: list[int], has_battery: bool) -> tuple[bool, str]:
    """Decide si es portátil combinando chasis SMBIOS y presencia de batería."""
    portable_chassis = bool(PORTABLE_CHASSIS & set(chassis))
    if portable_chassis and has_battery:
        return True, "chasis portátil + batería"
    if has_battery:
        return True, "tiene batería (chasis no concluyente)"
    if portable_chassis:
        # Algunos portátiles/mini-PC reportan mal; sin batería lo tratamos como sobremesa.
        return False, "chasis portátil pero sin batería"
    return False, "sin batería y chasis de sobremesa"


def gpu_kind(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("nvidia", "geforce", "rtx", "gtx", "radeon rx", "arc ")):
        return "dedicada"
    if any(k in n for k in ("radeon(tm) graphics", "radeon graphics", "vega", "uhd", "iris", "intel(r) hd")):
        return "integrada"
    return "desconocida"


def windows_label(build: int, display_version: str | None) -> str:
    # El registro sigue diciendo "Windows 10" en Windows 11; la build 22000+ es Windows 11.
    name = "Windows 11" if build >= 22000 else "Windows 10"
    return f"{name} {display_version or ''} (build {build})".replace("  ", " ")


# --- Lectura real -----------------------------------------------------------

def _windows_info() -> str:
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    try:
        build = int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
        try:
            display = winreg.QueryValueEx(key, "DisplayVersion")[0]
        except FileNotFoundError:
            display = None
    finally:
        winreg.CloseKey(key)
    return windows_label(build, display)


def _vram_by_name() -> dict[str, float]:
    """VRAM real desde el registro (Win32_VideoController.AdapterRAM se corta a 4 GB)."""
    result: dict[str, float] = {}
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return result
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            k = winreg.OpenKey(root, sub)
            desc = winreg.QueryValueEx(k, "DriverDesc")[0]
            mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
            if isinstance(mem, bytes):
                mem = int.from_bytes(mem, "little")
            result[desc] = round(int(mem) / 1024**3, 1)
        except OSError:
            continue
    return result


def detect_system() -> SystemInfo:
    raw = powershell_json(_SCRIPT) or {}
    power = read_power_status()

    chassis = [int(c) for c in as_list(raw.get("chassis"))]
    is_laptop, reason = classify_laptop(chassis, power.has_battery)

    cpus = as_list(raw.get("cpu"))
    cpu = None
    if cpus:
        c = cpus[0]
        cpu = CpuInfo(
            name=(c.get("Name") or "").strip(),
            cores=int(c.get("NumberOfCores") or 0),
            threads=int(c.get("NumberOfLogicalProcessors") or 0),
            max_mhz=int(c.get("MaxClockSpeed") or 0),
        )

    vram = _vram_by_name()
    gpus = []
    for g in as_list(raw.get("gpu")):
        name = (g.get("Name") or "").strip()
        gpus.append(GpuInfo(name, g.get("DriverVersion") or "?", vram.get(name), gpu_kind(name)))

    sticks = as_list(raw.get("ram"))
    ram_speeds = [s.get("ConfiguredClockSpeed") or s.get("Speed") for s in sticks]
    ram_speeds = [int(s) for s in ram_speeds if s]

    disks = [
        DiskInfo(
            name=(d.get("FriendlyName") or "?").strip(),
            kind="NVMe" if d.get("BusType") == "NVMe" else (d.get("MediaType") or "?"),
            size_gb=round((d.get("Size") or 0) / 1000**3),
        )
        for d in as_list(raw.get("disks"))
    ]

    battery = None
    if power.has_battery:
        full = as_list(raw.get("batt_full"))
        static = as_list(raw.get("batt_static"))
        cycles = as_list(raw.get("batt_cycles"))
        battery = BatteryInfo(
            design_mwh=(static[0].get("DesignedCapacity") if static else None),
            full_mwh=(full[0].get("FullChargedCapacity") if full else None),
            cycles=(cycles[0].get("CycleCount") if cycles else None),
        )

    system = raw.get("system") or {}
    return SystemInfo(
        manufacturer=(system.get("Manufacturer") or "?").strip(),
        model=(system.get("Model") or "?").strip(),
        is_laptop=is_laptop,
        laptop_reason=reason,
        windows=_windows_info(),
        cpu=cpu,
        gpus=gpus,
        ram_gb=round(psutil.virtual_memory().total / 1024**3, 1),
        ram_speed_mhz=max(ram_speeds) if ram_speeds else None,
        disks=disks,
        battery=battery,
        power=power,
        power_scheme=active_power_scheme(),
    )
