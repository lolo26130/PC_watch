"""Collecteurs locaux : métriques, journaux, SMART, capteurs."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import psutil

from .config import Config
from .models import Collected, FailedUnit, LogLine, Metric
from .rules import guess_severity

ISO_RE = re.compile(r"^(\d{4}-\d\d-\d\d[T ][0-9:.+\-]+)")
SYSLOG_RE = re.compile(r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d)")
KERNEL_RE = re.compile(r"^\[\s*(\d+\.\d+)\]\s*(.*)$")


def run_cmd(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"commande introuvable: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout ({timeout}s): {' '.join(cmd)}"
    except OSError as exc:
        return 1, "", str(exc)


def _status(value: float, warn: float, crit: float, invert: bool = False) -> str:
    if invert:
        if value <= crit:
            return "critical"
        if value <= warn:
            return "warning"
        return "ok"
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warning"
    return "ok"


def _metric(
    metrics: list[Metric],
    key: str,
    label: str,
    value: float | int | str,
    unit: str = "",
    status: str = "ok",
    detail: str = "",
) -> None:
    metrics.append(Metric(key=key, label=label, value=value, unit=unit, status=status, detail=detail))


def _tail_lines(path: str, n: int) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block = min(end, max(64 * 1024, n * 512))
            f.seek(max(0, end - block))
            data = f.read()
        lines = data.splitlines()
        if end > block and lines:
            lines = lines[1:]
        return lines[-n:]
    except OSError:
        return []


def _log_timestamp(line: str) -> str:
    m = ISO_RE.match(line)
    if m:
        return m.group(1)
    m = SYSLOG_RE.match(line)
    if m:
        return m.group(1)
    m = KERNEL_RE.match(line)
    if m:
        return m.group(1)
    return ""


def _strip_timestamp(line: str) -> str:
    """Retire l'horodatage de tête pour l'affichage et la recherche."""
    m = ISO_RE.match(line)
    if m:
        return line[m.end():].lstrip()
    m = SYSLOG_RE.match(line)
    if m:
        return line[m.end():].lstrip()
    m = KERNEL_RE.match(line)
    if m:
        return m.group(2).strip()
    return line


def _priority_severity(priority: int) -> str:
    if priority <= 2:
        return "critical"
    if priority <= 4:
        return "warning"
    return "info"


def too_old(timestamp: str, config: Config) -> bool:
    """True si l'horodatage ISO est plus vieux que logs.max_age_hours."""
    if not timestamp:
        return False
    try:
        max_age = float(config.logs.get("max_age_hours", 24))
    except (TypeError, ValueError):
        max_age = 24
    if max_age <= 0:
        return False
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return (datetime.now() - parsed).total_seconds() > max_age * 3600


def _uptime_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}j {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def collect_system_metrics(config: Config, collected: Collected) -> None:
    metrics = collected.metrics
    thresholds = config.thresholds

    try:
        cpu = psutil.cpu_percent(interval=0.15)
        cpu_warn = config.thresholds_for("cpu_warn_percent", 90)
        cpu_crit = config.thresholds_for("cpu_crit_percent", 98)
        _metric(metrics, "cpu", "CPU", cpu, "%", _status(cpu, cpu_warn, cpu_crit))
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"CPU: {exc}")

    try:
        mem = psutil.virtual_memory()
        mem_warn = config.thresholds_for("mem_warn_percent", 85)
        mem_crit = config.thresholds_for("mem_crit_percent", 95)
        _metric(
            metrics,
            "mem",
            "Mémoire",
            mem.percent,
            "%",
            _status(mem.percent, mem_warn, mem_crit),
            f"{mem.used / 1024**3:.1f}G utilisés / {mem.total / 1024**3:.1f}G",
        )
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"Mémoire: {exc}")

    try:
        swap = psutil.swap_memory()
        swap_warn = config.thresholds_for("swap_warn_percent", 50)
        swap_crit = config.thresholds_for("swap_crit_percent", 80)
        if swap.total:
            _metric(
                metrics,
                "swap",
                "Swap",
                swap.percent,
                "%",
                _status(swap.percent, swap_warn, swap_crit),
                f"{swap.used / 1024**3:.1f}G / {swap.total / 1024**3:.1f}G",
            )
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"Swap: {exc}")

    try:
        load1, load5, load15 = os.getloadavg()
        cpus = max(1, psutil.cpu_count() or 1)
        warn = config.thresholds_for("load_warn_per_cpu", 1.5) * cpus
        crit = config.thresholds_for("load_crit_per_cpu", 3.0) * cpus
        _metric(
            metrics,
            "load",
            "Charge",
            round(load1, 2),
            "",
            _status(load1, warn, crit),
            f"load1={load1:.2f} load5={load5:.2f} load15={load15:.2f} / {cpus} CPU",
        )
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"Load: {exc}")

    try:
        boot = psutil.boot_time()
        uptime = time.time() - boot
        collected.meta["uptime_seconds"] = uptime
        collected.meta["uptime"] = _uptime_text(uptime)
        collected.meta["boot_time"] = datetime.fromtimestamp(boot).isoformat(timespec="seconds")
        _metric(metrics, "uptime", "Uptime", collected.meta["uptime"], status="info")
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"Uptime: {exc}")

    seen_mounts: set[str] = set()
    try:
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if mount in seen_mounts:
                continue
            if part.fstype in ("tmpfs", "devtmpfs", "proc", "sysfs", "cgroup", "cgroup2", "squashfs"):
                continue
            try:
                usage = psutil.disk_usage(mount)
            except (PermissionError, OSError):
                continue
            seen_mounts.add(mount)
            warn = config.thresholds_for("disk_warn_percent", 85)
            crit = config.thresholds_for("disk_crit_percent", 95)
            _metric(
                metrics,
                f"disk:{mount}",
                f"Disque {mount}",
                usage.percent,
                "%",
                _status(usage.percent, warn, crit),
                f"{usage.used / 1024**3:.1f}G utilisés / {usage.total / 1024**3:.1f}G "
                f"({usage.free / 1024**3:.1f}G libres, {part.fstype})",
            )
    except Exception as exc:  # noqa: BLE001
        collected.errors.append(f"Disques: {exc}")


def _add_temp(
    config: Config,
    collected: Collected,
    chip: str,
    label: str,
    value: float,
    high: float | None = None,
    critical: float | None = None,
) -> None:
    warn = float(high) if high and high > 0 else config.thresholds_for("temp_warn_c", 75)
    crit = float(critical) if critical and critical > 0 else config.thresholds_for("temp_crit_c", 90)
    status = _status(value, warn, crit)
    display = f"{chip} {label}".strip()
    _metric(
        collected.metrics,
        f"temp:{chip}:{label}",
        f"Temp {display}",
        round(value, 1),
        "°C",
        status,
        f"seuils warn={warn:.0f}°C crit={crit:.0f}°C",
    )
    collected.sensors[display] = value


def collect_sensors(config: Config, collected: Collected) -> None:
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for chip, entries in temps.items():
                for entry in entries:
                    if entry.current is None:
                        continue
                    label = entry.label or "temp"
                    _add_temp(
                        config,
                        collected,
                        chip,
                        label,
                        float(entry.current),
                        entry.high,
                        entry.critical,
                    )
            return
    except Exception:  # noqa: BLE001 - fallback sensors
        pass

    if not shutil.which("sensors"):
        return
    code, out, _ = run_cmd(["sensors", "-j"], timeout=5)
    if code == 0 and out.strip().startswith("{"):
        try:
            data = json.loads(out)
            for chip, values in data.items():
                if not isinstance(values, dict):
                    continue
                for key, value in values.items():
                    if not isinstance(value, dict):
                        continue
                    for subkey, subvalue in value.items():
                        if subkey.endswith("_input") and isinstance(subvalue, (int, float)):
                            _add_temp(config, collected, chip, key, float(subvalue))
            return
        except (ValueError, TypeError):
            pass

    code, out, _ = run_cmd(["sensors"], timeout=5)
    if code == 0:
        for line in out.splitlines():
            m = re.match(r"^\s*([^:]+):\s+\+?([0-9.]+)°C", line)
            if m:
                _add_temp(config, collected, "sensors", m.group(1).strip(), float(m.group(2)))


# ---------------------------------------------------------------------------
# Journaux
# ---------------------------------------------------------------------------

def collect_journal(config: Config, collected: Collected) -> None:
    if not config.logs.get("journal", True):
        return
    if not shutil.which("journalctl"):
        collected.errors.append("journalctl absent : journaux systemd non lus")
        return
    priority = str(config.logs.get("journal_priority", "warning"))
    max_lines = int(config.logs.get("journal_max_lines", 300))
    cmd = [
        "journalctl",
        "-p", priority,
        "-b",
        "--no-pager",
        "-o", "json",
        "-n", str(max_lines),
    ]
    code, out, err = run_cmd(cmd, timeout=10)
    if code != 0:
        collected.errors.append(f"journalctl: {(err or out).strip()[:200]}")
        return
    seen: set[tuple[str, str, str]] = set()
    for line in out.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        message = str(item.get("MESSAGE", "")).strip()
        if not message:
            continue
        try:
            priority_num = int(item.get("PRIORITY", 6))
        except (TypeError, ValueError):
            priority_num = 6
        unit = item.get("_SYSTEMD_UNIT") or item.get("SYSLOG_IDENTIFIER") or item.get("_TRANSPORT") or "journal"
        timestamp = ""
        raw_ts = item.get("__REALTIME_TIMESTAMP")
        if raw_ts:
            try:
                timestamp = datetime.fromtimestamp(int(raw_ts) / 1_000_000).isoformat(timespec="seconds")
            except (TypeError, ValueError, OSError):
                timestamp = str(raw_ts)
        if too_old(timestamp, config):
            continue
        key = (timestamp, str(unit), message)
        if key in seen:
            continue
        seen.add(key)
        collected.logs.append(
            LogLine(
                timestamp=timestamp,
                source=f"journal:{unit}",
                message=message,
                raw=message,
                severity=_priority_severity(priority_num),
            )
        )


def collect_files(config: Config, collected: Collected) -> None:
    max_lines = int(config.logs.get("max_lines_per_source", 200))
    seen: set[tuple[str, str]] = set()
    for file_name in config.logs.get("files", []):
        path = Path(file_name)
        if not path.is_file():
            continue
        try:
            if not os.access(path, os.R_OK):
                collected.errors.append(f"log illisible: {path}")
                continue
        except OSError:
            continue
        for line in _tail_lines(str(path), max_lines):
            if not line.strip():
                continue
            timestamp = _log_timestamp(line)
            if too_old(timestamp, config):
                continue
            key = (str(path), line)
            if key in seen:
                continue
            seen.add(key)
            collected.logs.append(
                LogLine(
                    timestamp=timestamp,
                    source=path.name,
                    message=_strip_timestamp(line),
                    raw=line,
                    severity=guess_severity(line),
                )
            )


def collect_dmesg(config: Config, collected: Collected) -> None:
    if not config.logs.get("dmesg", True):
        return
    if not shutil.which("dmesg"):
        return
    code, out, err = run_cmd(["dmesg", "--color=never"], timeout=5)
    if code != 0:
        # dmesg est souvent restreint ; journalctl -k couvre déjà le noyau.
        if "permission" in (err or "").lower() or "operation not permitted" in (err or "").lower():
            collected.errors.append("dmesg: permissions insuffisantes (kernel.dmesg_restrict)")
        return
    max_lines = int(config.logs.get("max_lines_per_source", 200))
    seen: set[str] = set()
    for line in out.splitlines()[-max_lines:]:
        m = KERNEL_RE.match(line)
        message = m.group(2) if m else line
        if message in seen:
            continue
        seen.add(message)
        collected.logs.append(
            LogLine(
                timestamp=m.group(1) if m else "",
                source="kernel",
                message=message,
                raw=line,
                severity=guess_severity(message),
            )
        )


# ---------------------------------------------------------------------------
# Services, SMART
# ---------------------------------------------------------------------------

def collect_failed_units(collected: Collected) -> list[FailedUnit]:
    if not shutil.which("systemctl"):
        return []
    code, out, err = run_cmd(["systemctl", "--failed", "--no-legend", "--no-pager"], timeout=5)
    if code != 0:
        if err.strip():
            collected.errors.append(f"systemctl --failed: {err.strip()[:200]}")
        return []
    units: list[FailedUnit] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("●"):
            line = line[1:].strip()
        parts = line.split()
        if len(parts) < 4:
            continue
        units.append(
            FailedUnit(
                unit=parts[0],
                load=parts[1],
                active=parts[2],
                sub=parts[3],
                description=" ".join(parts[4:]),
            )
        )
    if units:
        _metric(
            collected.metrics,
            "failed_units",
            "Services en échec",
            len(units),
            "",
            "warning",
            ", ".join(u.unit for u in units[:5]),
        )
    return units


def _smart_number(text: str) -> int | None:
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def parse_smart_output(device: str, output: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "device": device,
        "model": "",
        "serial": "",
        "pending": 0,
        "reallocated": 0,
        "uncorrectable": 0,
        "temp_c": None,
        "used_percent": None,
        "critical_warning": 0,
        "media_errors": 0,
        "available_spare": None,
        "power_on_hours": None,
        "raw": output,
    }
    for line in output.splitlines():
        m = re.search(r"(?:Device Model|Model Number):\s*(.+)", line)
        if m:
            data["model"] = m.group(1).strip()
        m = re.search(r"Serial Number:\s*(.+)", line)
        if m:
            data["serial"] = m.group(1).strip()
        m = re.search(r"Critical Warning:\s*(0x[0-9a-fA-F]+|\d+)", line)
        if m:
            try:
                data["critical_warning"] = int(m.group(1), 0)
            except ValueError:
                data["critical_warning"] = 0
        m = re.search(r"Temperature:\s*(\d+)\s+Celsius", line)
        if m:
            data["temp_c"] = int(m.group(1))
        m = re.search(r"Available Spare:\s*(\d+)%", line)
        if m:
            data["available_spare"] = int(m.group(1))
        m = re.search(r"Percentage Used:\s*(\d+)%", line)
        if m:
            data["used_percent"] = int(m.group(1))
        m = re.search(r"Media and Data Integrity Errors:\s*([\d,]+)", line)
        if m:
            data["media_errors"] = int(m.group(1).replace(",", ""))
        m = re.search(r"Error Information Log Entries:\s*([\d,]+)", line)
        if m and not data.get("media_errors"):
            data["media_errors"] = int(m.group(1).replace(",", ""))
        m = re.search(r"Power On Hours:\s*([\d,]+)", line)
        if m:
            data["power_on_hours"] = int(m.group(1).replace(",", ""))
        # Attributs ATA : "ID NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN RAW"
        m = re.match(
            r"^\s*\d+\s+(Reallocated_Sector_Ct|Current_Pending_Sector|"
            r"Offline_Uncorrectable|Temperature_Celsius|Power_On_Hours|"
            r"Wear_Leveling_Count|Media_Wearout_Indicator)\s+"
            r"0x[0-9a-fA-F]+\s+\d+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+(.+)$",
            line,
        )
        if m:
            name = m.group(1)
            raw = m.group(2).strip()
            value = _smart_number(raw)
            if name == "Reallocated_Sector_Ct" and value is not None:
                data["reallocated"] = value
            elif name == "Current_Pending_Sector" and value is not None:
                data["pending"] = value
            elif name == "Offline_Uncorrectable" and value is not None:
                data["uncorrectable"] = value
            elif name == "Temperature_Celsius" and value is not None:
                data["temp_c"] = value
            elif name == "Power_On_Hours" and value is not None:
                data["power_on_hours"] = value
            elif name in ("Wear_Leveling_Count", "Media_Wearout_Indicator") and value is not None:
                # Les attributs d'usure ATA sont normalisés : 100 = neuf.
                data["used_percent"] = max(0, min(100, 100 - value)) if value <= 100 else value
    return data


def add_smart_metrics(config: Config, data: dict[str, Any], collected: Collected) -> None:
    """Ajoute les métriques SMART d'un disque déjà parsé (local ou distant)."""
    dev = str(data.get("device", "?"))
    label = f"{dev} {data.get('model', '')}".strip()
    if data.get("pending", 0) > 0:
        _metric(
            collected.metrics,
            f"smart:{dev}:pending",
            f"SMART {label} — secteurs en attente",
            data["pending"],
            "",
            "critical",
            "secteurs instables en attente de réallocation",
        )
    if data.get("reallocated", 0) > 0:
        _metric(
            collected.metrics,
            f"smart:{dev}:reallocated",
            f"SMART {label} — secteurs réalloués",
            data["reallocated"],
            "",
            "warning",
            "secteurs déjà réalloués",
        )
    if data.get("uncorrectable", 0) > 0:
        _metric(
            collected.metrics,
            f"smart:{dev}:uncorrectable",
            f"SMART {label} — secteurs non corrigeables",
            data["uncorrectable"],
            "",
            "critical",
            "secteurs illisibles",
        )
    if data.get("media_errors", 0) > 0:
        _metric(
            collected.metrics,
            f"smart:{dev}:media_errors",
            f"SMART {label} — erreurs média",
            data["media_errors"],
            "",
            "critical",
            "erreurs d'intégrité de données",
        )
    if data.get("critical_warning", 0):
        _metric(
            collected.metrics,
            f"smart:{dev}:critical_warning",
            f"SMART {label} — alerte critique",
            data["critical_warning"],
            "",
            "critical",
            "Critical Warning SMART non nul",
        )
    if data.get("available_spare") is not None and data["available_spare"] < 10:
        _metric(
            collected.metrics,
            f"smart:{dev}:available_spare",
            f"SMART {label} — spare disponible",
            data["available_spare"],
            "%",
            "warning",
            "réserve de blocs faible",
        )
    if data.get("temp_c") is not None:
        warn = config.thresholds_for("smart_temp_warn_c", 60)
        crit = config.thresholds_for("smart_temp_crit_c", 75)
        _metric(
            collected.metrics,
            f"smart:{dev}:temp",
            f"SMART {label} — température",
            data["temp_c"],
            "°C",
            _status(float(data["temp_c"]), warn, crit),
            f"seuils warn={warn:.0f}°C crit={crit:.0f}°C",
        )
    if data.get("used_percent") is not None:
        warn = config.thresholds_for("smart_wear_warn_percent", 80)
        crit = config.thresholds_for("smart_wear_crit_percent", 95)
        _metric(
            collected.metrics,
            f"smart:{dev}:used",
            f"SMART {label} — usure",
            data["used_percent"],
            "%",
            _status(float(data["used_percent"]), warn, crit),
            f"usure estimée ; seuils warn={warn:.0f}% crit={crit:.0f}%",
        )


def collect_smart(config: Config, host_smart: bool, host_sudo: bool, collected: Collected) -> dict[str, Any]:
    if not host_smart:
        return {}
    smartctl = shutil.which("smartctl") or "/usr/sbin/smartctl"
    if not Path(smartctl).exists():
        collected.errors.append("smartctl absent : SMART non lu")
        return {}
    code, out, err = run_cmd([smartctl, "--scan"], timeout=5)
    if code != 0 and not out:
        collected.errors.append(f"smartctl --scan: {(err or '').strip()[:160]}")
        return {}
    devices: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        dev = line.split()[0]
        if dev.startswith("/dev/"):
            devices.append(dev)
    result: dict[str, Any] = {}
    permission_error = False
    for dev in devices:
        cmd = [smartctl, "-a", dev]
        if host_sudo:
            cmd = ["sudo", "-n", *cmd]
        code, output, err = run_cmd(cmd, timeout=8)
        combined = (output or "") + "\n" + (err or "")
        if code != 0 and not output.strip():
            low = combined.lower()
            if "permission" in low or "operation not permitted" in low or "must be root" in low:
                permission_error = True
            else:
                collected.errors.append(f"SMART {dev}: {combined.strip()[:160]}")
            continue
        if not output.strip():
            continue
        data = parse_smart_output(dev, output)
        result[dev] = data
        label = f"{dev} {data.get('model', '')}".strip()
        if data.get("pending", 0) > 0:
            _metric(
                collected.metrics,
                f"smart:{dev}:pending",
                f"SMART {label} — secteurs en attente",
                data["pending"],
                "",
                "critical",
                "secteurs instables en attente de réallocation",
            )
        if data.get("reallocated", 0) > 0:
            _metric(
                collected.metrics,
                f"smart:{dev}:reallocated",
                f"SMART {label} — secteurs réalloués",
                data["reallocated"],
                "",
                "warning",
                "secteurs déjà réalloués",
            )
        if data.get("uncorrectable", 0) > 0:
            _metric(
                collected.metrics,
                f"smart:{dev}:uncorrectable",
                f"SMART {label} — secteurs non corrigeables",
                data["uncorrectable"],
                "",
                "critical",
                "secteurs illisibles",
            )
        if data.get("media_errors", 0) > 0:
            _metric(
                collected.metrics,
                f"smart:{dev}:media_errors",
                f"SMART {label} — erreurs média",
                data["media_errors"],
                "",
                "critical",
                "erreurs d'intégrité de données",
            )
        if data.get("critical_warning", 0):
            _metric(
                collected.metrics,
                f"smart:{dev}:critical_warning",
                f"SMART {label} — alerte critique",
                data["critical_warning"],
                "",
                "critical",
                "Critical Warning SMART non nul",
            )
        if data.get("available_spare") is not None and data["available_spare"] < 10:
            _metric(
                collected.metrics,
                f"smart:{dev}:available_spare",
                f"SMART {label} — spare disponible",
                data["available_spare"],
                "%",
                "warning",
                "réserve de blocs faible",
            )
        if data.get("temp_c") is not None:
            warn = config.thresholds_for("smart_temp_warn_c", 60)
            crit = config.thresholds_for("smart_temp_crit_c", 75)
            _metric(
                collected.metrics,
                f"smart:{dev}:temp",
                f"SMART {label} — température",
                data["temp_c"],
                "°C",
                _status(float(data["temp_c"]), warn, crit),
                f"seuils warn={warn:.0f}°C crit={crit:.0f}°C",
            )
        if data.get("used_percent") is not None:
            warn = config.thresholds_for("smart_wear_warn_percent", 80)
            crit = config.thresholds_for("smart_wear_crit_percent", 95)
            _metric(
                collected.metrics,
                f"smart:{dev}:used",
                f"SMART {label} — usure",
                data["used_percent"],
                "%",
                _status(float(data["used_percent"]), warn, crit),
                f"usure estimée ; seuils warn={warn:.0f}% crit={crit:.0f}%",
            )
    if permission_error:
        collected.errors.append(
            "SMART: permissions insuffisantes (activer smart_sudo=true ou lancer avec sudo)"
        )
    return result


# ---------------------------------------------------------------------------
# Collecte locale complète
# ---------------------------------------------------------------------------

def collect_local(config: Config, host_name: str = "local") -> Collected:
    collected = Collected(host=host_name, host_type="local")
    try:
        collected.meta["hostname"] = socket.gethostname()
    except OSError:
        collected.meta["hostname"] = host_name
    try:
        uname = platform.uname()
        collected.meta["uname"] = f"{uname.system} {uname.release} {uname.machine}"
    except Exception:  # noqa: BLE001
        collected.meta["uname"] = ""
    collected.meta["cpu_count"] = psutil.cpu_count() or 1

    collect_system_metrics(config, collected)
    collect_sensors(config, collected)
    collected.failed_units = collect_failed_units(collected)
    local_host = config.hosts.get("local")
    collected.smart = collect_smart(
        config,
        local_host.smart if local_host else True,
        local_host.smart_sudo if local_host else False,
        collected,
    )
    collect_journal(config, collected)
    collect_files(config, collected)
    collect_dmesg(config, collected)
    return collected
