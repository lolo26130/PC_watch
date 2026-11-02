"""Le « médecin » : transformation des constats en explication lisible."""

from __future__ import annotations

from .models import HealthReport, SEVERITY_EMOJI, SEVERITY_LABEL

AREA_LABELS = {
    "disk": "Disque",
    "filesystem": "Système de fichiers",
    "memory": "Mémoire",
    "cpu": "CPU",
    "thermal": "Température",
    "power": "Alimentation",
    "services": "Services",
    "network": "Réseau",
    "security": "Sécurité",
    "kernel": "Noyau",
    "boot": "Démarrage",
    "smart": "SMART",
    "collect": "Collecte",
    "custom": "Divers",
}


def health_bar(score: int, width: int = 20) -> str:
    filled = max(0, min(width, round(score * width / 100)))
    return "█" * filled + "░" * (width - filled)


def area_label(area: str) -> str:
    return AREA_LABELS.get(area, area.capitalize())


def summary_line(report: HealthReport) -> str:
    return f"🩺 {report.score}/100 — {report.verdict}"


def vitals_line(report: HealthReport) -> str:
    by_key = {m.key: m for m in report.metrics}
    values: list[str] = []
    if "cpu" in by_key:
        values.append(f"CPU {by_key['cpu'].display()}")
    if "mem" in by_key:
        values.append(f"RAM {by_key['mem'].display()}")
    if "load" in by_key:
        values.append(f"Load {by_key['load'].display()}")
    root = next((m for m in report.metrics if m.key == "disk:/"), None)
    if root:
        values.append(f"/ {root.display()}")
    temps = [m for m in report.metrics if m.key.startswith("temp:")]
    if temps:
        hottest = max(temps, key=lambda m: float(m.value) if isinstance(m.value, (int, float)) else 0)
        values.append(f"{hottest.label.replace('Temp ', '')} {hottest.display()}")
    return " · ".join(values)


def _bullet(finding, simplicity: str) -> str:
    emoji = SEVERITY_EMOJI.get(finding.severity, "•")
    label = SEVERITY_LABEL.get(finding.severity, finding.severity.upper())
    text = finding.text(simplicity)
    if simplicity == "simple":
        return f"{emoji} {text}"
    return f"{emoji} [{label}] {area_label(finding.area)} — {text}"


def doctor_text(
    report: HealthReport,
    simplicity: str = "normal",
    verbosity: str = "normal",
) -> str:
    """Rapport narratif « Dr. PC » adapté au niveau de simplicité/verbosité."""

    simplicity = (simplicity or "normal").lower()
    verbosity = (verbosity or "normal").lower()
    lines: list[str] = [
        f"🩺 Dr. PC — consultation de {report.host}",
        f"État général : {health_bar(report.score)} {report.score}/100",
        report.verdict + ".",
        "",
    ]

    findings = report.findings
    if not findings:
        lines.append("Aucun symptôme important détecté dans les journaux récents.")
        lines.append("Les constantes sont normales ou sans gravité.")
        return "\n".join(lines)

    if verbosity == "quiet":
        finding = findings[0]
        lines.append(_bullet(finding, "simple"))
        if finding.advice:
            lines.extend(["", f"Conseil : {finding.advice}"])
        return "\n".join(lines)

    if simplicity == "simple":
        for finding in findings[:2]:
            lines.append(_bullet(finding, "simple"))
        advice = next((f.advice for f in findings if f.advice), "")
        if advice:
            lines.extend(["", f"Conseil : {advice}"])
        return "\n".join(lines)

    lines.append("Symptômes :")
    shown = 0
    for finding in findings:
        if simplicity == "normal" and finding.severity == "info" and verbosity not in ("verbose", "debug"):
            continue
        lines.append(_bullet(finding, simplicity))
        if verbosity in ("verbose", "debug"):
            for evidence in finding.evidence[:3]:
                lines.append(f"   ↳ {evidence}")
        shown += 1
        if simplicity == "normal" and shown >= 8:
            break

    if shown == 0:
        lines.append("Rien de grave détecté ; quelques informations mineures seulement.")
        return "\n".join(lines)

    commands: list[str] = []
    for finding in findings:
        for command in finding.commands:
            if command not in commands:
                commands.append(command)
    if commands:
        lines.extend(["", "Ordonnance :"])
        for command in commands[:6]:
            lines.append(f"  → {command}")

    if verbosity in ("verbose", "debug"):
        lines.extend(["", "Constantes :"])
        for metric in report.metrics:
            if metric.key in ("uptime",):
                continue
            state = "" if metric.status == "ok" else f"  [{metric.status}]"
            lines.append(f"  • {metric.label}: {metric.display()}{state}")
    if verbosity == "debug":
        lines.extend(["", "Notes techniques :"])
        lines.append(
            f"  logs={report.stats.get('logs', 0)} metrics={report.stats.get('metrics', 0)} "
            f"findings={report.stats.get('findings', 0)}"
        )
        for error in report.errors:
            lines.append(f"  ! {error}")
    elif verbosity == "verbose" and report.errors:
        lines.extend(["", "Notes :"])
        for error in report.errors[:5]:
            lines.append(f"  ! {error}")

    if simplicity == "expert":
        lines.extend(["", "Données brutes utiles :"])
        lines.append(f"  collected_at={report.collected_at} generated_at={report.generated_at}")
        for key, value in report.stats.get("host_meta", {}).items():
            lines.append(f"  {key}={value}")

    return "\n".join(lines)
