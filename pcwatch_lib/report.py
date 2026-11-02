"""Rendu terminal Rich et sortie JSON."""

from __future__ import annotations

import json
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .doctor import doctor_text, health_bar, summary_line, vitals_line
from .models import HealthReport, SEVERITY_LABEL

SEVERITY_STYLE = {
    "info": "cyan",
    "warning": "yellow",
    "critical": "bold red",
}
STATUS_STYLE = {
    "ok": "green",
    "info": "cyan",
    "warning": "yellow",
    "critical": "bold red",
}


def report_json(report: HealthReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _console(no_color: bool) -> Console:
    return Console(no_color=no_color, highlight=False)


def _header(report: HealthReport) -> Panel:
    title = Text()
    title.append("PC Watch", style="bold")
    title.append("  ")
    title.append(f"{report.host}", style="bold cyan")
    title.append(f"  ({report.host_type})\n", style="dim")
    title.append(f"{summary_line(report)}\n", style="bold")
    title.append(health_bar(report.score) + "\n", style="green")
    title.append(vitals_line(report) + "\n", style="")
    title.append(f"Dernière analyse : {report.generated_at}", style="dim")
    return Panel(title, box=box.ROUNDED, border_style="cyan")


def _findings_table(report: HealthReport, verbosity: str, simplicity: str) -> Table:
    table = Table(box=box.SIMPLE_HEAD, expand=True, show_lines=False)
    table.add_column("Gravité", no_wrap=True, width=9)
    table.add_column("Domaine", no_wrap=True, width=12)
    table.add_column("Constat", overflow="fold")
    table.add_column("Quand", no_wrap=True, width=19)

    findings = report.findings
    if verbosity == "quiet":
        findings = findings[:1]
    elif verbosity == "normal":
        findings = [f for f in findings if f.severity != "info"][:8]
    for finding in findings:
        label = f"{SEVERITY_LABEL.get(finding.severity, finding.severity.upper())}"
        text = finding.text(simplicity)
        if finding.count > 1:
            text += f"  (×{finding.count})"
        table.add_row(
            Text(label, style=SEVERITY_STYLE.get(finding.severity, "")),
            Text(finding.area, style="dim"),
            Text(text),
            Text(finding.timestamp or "—", style="dim"),
        )
    return table


def _metrics_table(report: HealthReport, verbosity: str) -> Table:
    table = Table(box=box.SIMPLE_HEAD, expand=True)
    table.add_column("Métrique", width=28)
    table.add_column("Valeur", width=12, justify="right")
    table.add_column("État", width=9)
    table.add_column("Détail", overflow="fold")

    metrics = report.metrics
    if verbosity == "quiet":
        metrics = [m for m in metrics if m.key in ("cpu", "mem", "disk:/")]
    elif verbosity == "normal":
        metrics = [m for m in metrics if m.status != "ok" or m.key in ("cpu", "mem", "load", "disk:/")]
    for metric in metrics:
        table.add_row(
            Text(metric.label),
            Text(metric.display()),
            Text(metric.status.upper(), style=STATUS_STYLE.get(metric.status, "")),
            Text(metric.detail, style="dim"),
        )
    return table


def _logs_panel(report: HealthReport, verbosity: str) -> Panel | None:
    if verbosity not in ("verbose", "debug"):
        return None
    limit = 30 if verbosity == "debug" else 12
    logs = report.logs[-limit:]
    if not logs:
        return None
    text = Text()
    for line in logs:
        style = SEVERITY_STYLE.get(line.severity, "")
        prefix = f"{line.timestamp} " if line.timestamp else ""
        text.append(prefix, style="dim")
        text.append(f"{line.source}: ", style="dim cyan")
        text.append(line.message[:240] + ("…" if len(line.message) > 240 else "") + "\n", style=style)
    return Panel(text, title=f"Journaux récents ({len(logs)})", border_style="dim")


def _errors_panel(report: HealthReport, verbosity: str) -> Panel | None:
    if not report.errors:
        return None
    if verbosity not in ("verbose", "debug"):
        return None
    limit = len(report.errors) if verbosity == "debug" else 6
    text = Text("\n".join(f"• {e}" for e in report.errors[:limit]), style="dim red")
    return Panel(text, title="Notes de collecte", border_style="red")


def render_report(
    report: HealthReport,
    verbosity: str = "normal",
    simplicity: str = "normal",
    no_color: bool = False,
) -> int:
    console = _console(no_color)
    console.print(_header(report))
    console.print(
        Panel(
            Text(doctor_text(report, simplicity, verbosity)),
            title="🩺 Dr. PC",
            border_style="green" if report.score >= 75 else "yellow" if report.score >= 50 else "red",
            box=box.ROUNDED,
        )
    )

    if report.findings:
        console.print(
            Panel(
                _findings_table(report, verbosity, simplicity),
                title="Constats",
                border_style="dim",
                box=box.ROUNDED,
            )
        )
    if report.metrics:
        console.print(
            Panel(
                _metrics_table(report, verbosity),
                title="Constantes",
                border_style="dim",
                box=box.ROUNDED,
            )
        )
    logs = _logs_panel(report, verbosity)
    if logs:
        console.print(logs)
    errors = _errors_panel(report, verbosity)
    if errors:
        console.print(errors)

    if verbosity == "debug":
        console.print(
            Panel(
                Text(json.dumps(report.stats, ensure_ascii=False, indent=2), style="dim"),
                title="Statistiques",
                border_style="dim",
            )
        )

    return report.exit_code()
