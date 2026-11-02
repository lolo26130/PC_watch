"""Collecte distante sans installation : script POSIX envoyé par SSH."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .collectors import (
    add_smart_metrics,
    parse_smart_output,
    too_old,
    _metric,
    _status,
    _strip_timestamp,
)
from .config import Config, HostConfig
from .models import Collected, FailedUnit, LogLine
from .rules import guess_severity

SECTION_RE = re.compile(r"^@@([A-Z_]+)\s*$")
ISO_RE = re.compile(r"^(\d{4}-\d\d-\d\d[T ][0-9:.+\-]+)\s+")


def build_remote_script(host: HostConfig) -> str:
    """Script shell minimal, en lecture seule, exécuté sur la machine distante."""

    smart_cmd = "sudo -n smartctl" if host.smart_sudo else "smartctl"
    smart_enabled = "1" if host.smart else "0"
    script = r"""set +e
echo '@@META'
hostname 2>/dev/null
uname -a 2>/dev/null
uptime 2>/dev/null
nproc 2>/dev/null

echo '@@JOURNAL'
if command -v journalctl >/dev/null 2>&1; then
  journalctl -p warning -b --no-pager -o short-iso -n 200 2>/dev/null
fi

echo '@@KERNEL'
if command -v dmesg >/dev/null 2>&1; then
  dmesg 2>/dev/null | tail -n 200
fi

echo '@@SYSLOG'
for f in /var/log/syslog /var/log/messages; do
  if [ -r "$f" ]; then
    tail -n 200 "$f"
  fi
done

echo '@@AUTH'
if [ -r /var/log/auth.log ]; then
  tail -n 200 /var/log/auth.log
fi

echo '@@DISK'
df -P -x tmpfs -x devtmpfs 2>/dev/null

echo '@@MEM'
free -m 2>/dev/null

echo '@@SENSORS'
if command -v sensors >/dev/null 2>&1; then
  sensors 2>/dev/null
fi

echo '@@SMART'
if [ "__SMART_ENABLED__" = "1" ] && command -v smartctl >/dev/null 2>&1; then
  smartctl --scan 2>/dev/null | while read -r dev rest; do
    case "$dev" in
      /dev/*)
        echo "##DEV $dev"
        __SMART_CMD__ -a "$dev" 2>/dev/null || true
        ;;
    esac
  done
fi

echo '@@FAILED'
if command -v systemctl >/dev/null 2>&1; then
  systemctl --failed --no-legend --no-pager 2>/dev/null
fi

echo '@@END'
"""
    return script.replace("__SMART_ENABLED__", smart_enabled).replace("__SMART_CMD__", smart_cmd)


def parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"RAW": []}
    current = "RAW"
    for line in output.splitlines():
        match = SECTION_RE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _parse_meta(section: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if lines:
        meta["hostname"] = lines[0]
    for line in lines:
        if " " in line and ("Linux" in line or "BSD" in line or "GNU" in line):
            meta["uname"] = line
        if "load average" in line or "up " in line:
            meta["uptime"] = line
        try:
            n = int(line)
            if 1 <= n <= 4096:
                meta["cpu_count"] = n
        except ValueError:
            continue
    return meta


def _parse_logs(config: Config, sections: dict[str, str], collected: Collected) -> None:
    seen: set[tuple[str, str]] = set()
    for section in ("JOURNAL", "KERNEL", "SYSLOG", "AUTH"):
        for line in sections.get(section, "").splitlines():
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            match = ISO_RE.match(line)
            timestamp = match.group(1) if match else ""
            if too_old(timestamp, config):
                continue
            key = (section, line)
            if key in seen:
                continue
            seen.add(key)
            collected.logs.append(
                LogLine(
                    timestamp=timestamp,
                    source=section.lower(),
                    message=_strip_timestamp(line),
                    raw=line,
                    severity=guess_severity(line),
                )
            )


def _parse_disk(config: Config, sections: dict[str, str], collected: Collected) -> None:
    warn = config.thresholds_for("disk_warn_percent", 85)
    crit = config.thresholds_for("disk_crit_percent", 95)
    for line in sections.get("DISK", "").splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0] == "Filesystem":
            continue
        mount = " ".join(parts[5:])
        capacity = parts[4].rstrip("%")
        try:
            percent = float(capacity)
        except ValueError:
            continue
        _metric(
            collected.metrics,
            f"disk:{mount}",
            f"Disque {mount}",
            percent,
            "%",
            _status(percent, warn, crit),
            f"{parts[2]} blocs utilisés / {parts[1]} (source distante)",
        )


def _parse_mem(config: Config, sections: dict[str, str], collected: Collected) -> None:
    mem_warn = config.thresholds_for("mem_warn_percent", 85)
    mem_crit = config.thresholds_for("mem_crit_percent", 95)
    swap_warn = config.thresholds_for("swap_warn_percent", 50)
    swap_crit = config.thresholds_for("swap_crit_percent", 80)
    for line in sections.get("MEM", "").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "Mem:" and len(parts) >= 3:
            try:
                total = float(parts[1])
                used = float(parts[2])
                available = float(parts[6]) if len(parts) > 6 else max(0.0, total - used)
                percent = 100.0 * (total - available) / total if total else 0.0
            except (ValueError, IndexError):
                continue
            _metric(
                collected.metrics,
                "mem",
                "Mémoire",
                round(percent, 1),
                "%",
                _status(percent, mem_warn, mem_crit),
                f"{used:.0f}M utilisés / {total:.0f}M (source distante)",
            )
        elif parts[0] == "Swap:" and len(parts) >= 3:
            try:
                total = float(parts[1])
                used = float(parts[2])
                percent = 100.0 * used / total if total else 0.0
            except (ValueError, IndexError):
                continue
            if total:
                _metric(
                    collected.metrics,
                    "swap",
                    "Swap",
                    round(percent, 1),
                    "%",
                    _status(percent, swap_warn, swap_crit),
                    f"{used:.0f}M / {total:.0f}M (source distante)",
                )


def _parse_sensors(config: Config, sections: dict[str, str], collected: Collected) -> None:
    warn = config.thresholds_for("temp_warn_c", 75)
    crit = config.thresholds_for("temp_crit_c", 90)
    for line in sections.get("SENSORS", "").splitlines():
        match = re.match(r"^\s*([^:]+):\s+\+?([0-9.]+)°C", line)
        if not match:
            continue
        label = match.group(1).strip()
        value = float(match.group(2))
        collected.sensors[label] = value
        _metric(
            collected.metrics,
            f"temp:remote:{label}",
            f"Temp {label}",
            value,
            "°C",
            _status(value, warn, crit),
            f"seuils warn={warn:.0f}°C crit={crit:.0f}°C (source distante)",
        )


def _parse_smart(config: Config, sections: dict[str, str], collected: Collected) -> None:
    current: str | None = None
    buffer: list[str] = []
    for line in sections.get("SMART", "").splitlines():
        if line.startswith("##DEV "):
            if current and buffer:
                data = parse_smart_output(current, "\n".join(buffer))
                collected.smart[current] = data
                add_smart_metrics(config, data, collected)
            current = line.split(maxsplit=1)[1].strip()
            buffer = []
            continue
        if current:
            buffer.append(line)
    if current and buffer:
        data = parse_smart_output(current, "\n".join(buffer))
        collected.smart[current] = data
        add_smart_metrics(config, data, collected)


def _parse_failed(sections: dict[str, str], collected: Collected) -> None:
    for line in sections.get("FAILED", "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("●"):
            line = line[1:].strip()
        parts = line.split()
        if len(parts) < 4:
            continue
        collected.failed_units.append(
            FailedUnit(
                unit=parts[0],
                load=parts[1],
                active=parts[2],
                sub=parts[3],
                description=" ".join(parts[4:]),
            )
        )
    if collected.failed_units:
        _metric(
            collected.metrics,
            "failed_units",
            "Services en échec",
            len(collected.failed_units),
            "",
            "warning",
            ", ".join(u.unit for u in collected.failed_units[:5]),
        )


def collect_remote(config: Config, host: HostConfig) -> Collected:
    collected = Collected(host=host.name, host_type="ssh")
    if not host.target:
        collected.errors.append(f"hôte SSH {host.name} sans cible (target)")
        return collected

    script = build_remote_script(host)
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={host.connect_timeout}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=5",
    ]
    if host.identity:
        cmd += ["-i", host.identity]
    if host.port != 22:
        cmd += ["-p", str(host.port)]
    cmd += host.ssh_options
    cmd += [host.target, "sh -s"]

    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=host.connect_timeout + 30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        collected.errors.append(f"SSH {host.target}: timeout")
        return collected
    except FileNotFoundError:
        collected.errors.append("ssh introuvable")
        return collected
    except OSError as exc:
        collected.errors.append(f"SSH {host.target}: {exc}")
        return collected

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        collected.errors.append(
            f"SSH {host.target}: {message[-1] if message else f'code {proc.returncode}'}"
        )
        return collected

    sections = parse_sections(proc.stdout)
    collected.raw_sections = sections
    if "END" not in sections:
        collected.errors.append("réponse SSH incomplète (marqueur @@END absent)")
    collected.meta = _parse_meta(sections.get("META", ""))
    collected.meta.setdefault("hostname", host.target)
    collected.meta["ssh"] = host.target
    _parse_logs(config, sections, collected)
    _parse_disk(config, sections, collected)
    _parse_mem(config, sections, collected)
    _parse_sensors(config, sections, collected)
    _parse_smart(config, sections, collected)
    _parse_failed(sections, collected)
    if not collected.metrics and not collected.logs and not collected.failed_units:
        collected.errors.append("aucune donnée exploitable sur l'hôte distant")
    return collected
