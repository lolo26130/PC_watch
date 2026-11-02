"""Données de démonstration pour tester la TUI sans toucher au système."""

from __future__ import annotations

from .models import Collected, FailedUnit, LogLine, Metric


def demo_collected() -> Collected:
    collected = Collected(host="demo-pc", host_type="demo")
    collected.meta = {
        "hostname": "demo-pc",
        "uname": "Linux 6.8.0-demo x86_64",
        "uptime": "2j 4h 12m",
        "uptime_seconds": 187920,
        "cpu_count": 8,
        "boot_time": "2026-10-31T18:35:00",
    }
    collected.metrics = [
        Metric("cpu", "CPU", 37.0, "%", "ok"),
        Metric("mem", "Mémoire", 72.0, "%", "ok", "11.5G utilisés / 16.0G"),
        Metric("swap", "Swap", 12.0, "%", "ok", "1.0G / 8.0G"),
        Metric("load", "Charge", 2.4, "", "ok", "load1=2.40 load5=1.90 load15=1.50 / 8 CPU"),
        Metric("disk:/", "Disque /", 91.0, "%", "warning", "1.6T utilisés / 1.8T (150G libres, ext4)"),
        Metric("disk:/home", "Disque /home", 55.0, "%", "ok", "500G utilisés / 1.0T"),
        Metric("temp:coretemp:Package id 0", "Temp coretemp Package id 0", 78.0, "°C", "warning", "seuils warn=75°C crit=90°C"),
        Metric("smart:/dev/nvme0n1:pending", "SMART /dev/nvme0n1 — secteurs en attente", 2, "", "critical", "secteurs instables en attente de réallocation"),
        Metric("smart:/dev/nvme0n1:reallocated", "SMART /dev/nvme0n1 — secteurs réalloués", 8, "", "warning", "secteurs déjà réalloués"),
        Metric("smart:/dev/nvme0n1:temp", "SMART /dev/nvme0n1 — température", 48, "°C", "ok", "seuils warn=60°C crit=75°C"),
        Metric("failed_units", "Services en échec", 1, "", "warning", "motd-news.service"),
        Metric("uptime", "Uptime", "2j 4h 12m", "", "info"),
    ]
    collected.sensors = {"coretemp Package id 0": 78.0, "nvme Composite": 48.0}
    collected.smart = {
        "/dev/nvme0n1": {
            "device": "/dev/nvme0n1",
            "model": "Demo NVMe 2TB",
            "serial": "DEMO-0001",
            "pending": 2,
            "reallocated": 8,
            "uncorrectable": 0,
            "temp_c": 48,
            "used_percent": 12,
            "critical_warning": 0,
            "media_errors": 0,
        }
    }
    collected.failed_units = [
        FailedUnit(
            unit="motd-news.service",
            load="loaded",
            active="failed",
            sub="failed",
            description="Message of the Day",
        )
    ]
    collected.logs = [
        LogLine(
            timestamp="2026-11-02T22:31:05",
            source="journal:kernel",
            message="nvme0n1: I/O error, dev nvme0n1, sector 123456 op 0x0:(READ) flags 0x0",
            raw="nvme0n1: I/O error, dev nvme0n1, sector 123456 op 0x0:(READ) flags 0x0",
            severity="critical",
        ),
        LogLine(
            timestamp="2026-11-02T22:32:11",
            source="journal:kernel",
            message="Out of memory: Killed process 4242 (firefox) total-vm:12000000kB",
            raw="Out of memory: Killed process 4242 (firefox) total-vm:12000000kB",
            severity="critical",
        ),
        LogLine(
            timestamp="2026-11-02T22:33:20",
            source="journal:systemd",
            message="Failed to start motd-news.service - Message of the Day.",
            raw="Failed to start motd-news.service - Message of the Day.",
            severity="warning",
        ),
        LogLine(
            timestamp="2026-11-02T22:34:02",
            source="journal:sshd",
            message="Failed password for invalid user admin from 203.0.113.7 port 51512 ssh2",
            raw="Failed password for invalid user admin from 203.0.113.7 port 51512 ssh2",
            severity="warning",
        ),
        LogLine(
            timestamp="2026-11-02T22:35:40",
            source="syslog",
            message="ata1: hard resetting link",
            raw="ata1: hard resetting link",
            severity="warning",
        ),
        LogLine(
            timestamp="2026-11-02T22:36:15",
            source="kernel",
            message="pcieport 0000:00:1c.0: AER: Corrected error received: 0000:00:1c.0",
            raw="pcieport 0000:00:1c.0: AER: Corrected error received: 0000:00:1c.0",
            severity="warning",
        ),
        LogLine(
            timestamp="2026-11-02T22:37:00",
            source="journal:NetworkManager",
            message="wlan0: link is down",
            raw="wlan0: link is down",
            severity="warning",
        ),
        LogLine(
            timestamp="2026-11-02T22:38:22",
            source="journal:systemd",
            message="motd-news.service: Failed with result 'exit-code'.",
            raw="motd-news.service: Failed with result 'exit-code'.",
            severity="warning",
        ),
    ]
    collected.errors = []
    return collected
