"""TUI Textual de PC Watch."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from .analyzer import collect_and_analyze
from .config import SIMPLICITIES, VERBOSITIES, Config, HostConfig
from .doctor import doctor_text, health_bar, vitals_line
from .models import Finding, HealthReport, SEVERITY_LABEL, SEVERITY_ORDER
from .rules import Rule, score_findings, verdict_for
from .terminal import (
    TerminalError,
    in_tmux,
    open_pane,
    pane_alive,
    run_interactive,
    send_literal,
)

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


class PCWatchApp(App):
    """Tableau de bord « Dr. PC »."""

    TITLE = "PC Watch"
    SUB_TITLE = "surveillance de santé"

    CSS = """
    #summary {
        height: 6;
        padding: 1 2;
        background: $boost;
    }
    #doctor {
        padding: 1 2;
        height: auto;
    }
    #findings {
        height: 1fr;
    }
    #finding-detail {
        height: auto;
        max-height: 12;
        padding: 1 2;
        color: $text-muted;
    }
    #metrics {
        height: 1fr;
    }
    #logs {
        height: 1fr;
    }
    #help {
        padding: 1 2;
    }
    #status {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("r", "refresh", "Rafraîchir"),
        Binding("a", "analyze", "Analyser"),
        Binding("v", "cycle_verbosity", "Verbosité"),
        Binding("s", "cycle_simplicity", "Simplicité"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("m", "cycle_host", "Hôte"),
        Binding("t", "terminal", "Term/SSH"),
        Binding("c", "send_command", "Cmd → term"),
        Binding("h", "help", "Aide"),
        Binding("q", "quit", "Quitter"),
    ]

    def __init__(
        self,
        config: Config,
        rules: list[Rule],
        host: HostConfig,
        verbosity: str | None = None,
        simplicity: str | None = None,
        demo: bool = False,
        rule_errors: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.rules = rules
        self.host = host
        self.verbosity = verbosity or config.verbosity
        self.simplicity = simplicity or config.simplicity
        self.demo = demo
        self.rule_errors = rule_errors or []
        self.paused = False
        self.last_report: Optional[HealthReport] = None
        self.history: dict[str, Finding] = {}
        self._finding_map: dict[str, Finding] = {}
        self._current_finding: Optional[Finding] = None
        self._term_panes: dict[str, str] = {}
        self.host_names = ["demo-pc"] if demo else config.host_names()
        try:
            self.host_index = self.host_names.index(host.name)
        except ValueError:
            self.host_index = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="summary")
        with TabbedContent(initial="tab-diagnostic"):
            with TabPane("Diagnostic", id="tab-diagnostic"):
                yield Static(id="doctor")
                yield DataTable(id="findings", cursor_type="row", zebra_stripes=True)
                yield Static(id="finding-detail")
            with TabPane("Capteurs", id="tab-metrics"):
                yield DataTable(id="metrics", zebra_stripes=True)
            with TabPane("Journaux", id="tab-logs"):
                yield RichLog(id="logs", markup=True, wrap=True)
            with TabPane("Hôte / Aide", id="tab-help"):
                yield Static(id="help")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._init_tables()
        self._update_help()
        self.set_interval(self.config.refresh_seconds, self.refresh_report)
        self.refresh_report()

    def _init_tables(self) -> None:
        findings = self.query_one("#findings", DataTable)
        findings.add_columns("Gravité", "Domaine", "Constat", "Quand")
        metrics = self.query_one("#metrics", DataTable)
        metrics.add_columns("Métrique", "Valeur", "État", "Détail")

    def _update_help(self) -> None:
        lines = [
            "PC Watch — aide",
            "",
            "Touches :",
            "  r   rafraîchir maintenant",
            "  a   analyser immédiatement",
            "  v   cycler quiet / normal / verbose / debug",
            "  s   cycler simple / normal / expert",
            "  p   pause / reprise du rafraîchissement périodique",
            "  m   changer d'hôte (local / SSH)",
            "  t   ouvrir un terminal local / SSH sur l'hôte analysé",
            "  c   taper la commande du constat dans ce terminal (sans l'exécuter)",
            "  h   cette aide",
            "  q   quitter",
            "",
            f"Config : {self.config.path}",
            f"Règles : {self.config.rules_path}",
            "",
            "Hôtes configurés : " + ", ".join(self.host_names),
            "",
            "Le rapport est une aide au diagnostic, pas un avis médical.",
        ]
        self.query_one("#help", Static).update(Text("\n".join(lines)))

    def refresh_report(self) -> None:
        if self.paused:
            return
        self.query_one("#status", Static).update(Text("Analyse en cours…", style="dim"))
        self._collect_worker()

    @work(thread=True, exclusive=True, group="collect")
    def _collect_worker(self) -> None:
        try:
            report = collect_and_analyze(
                self.config,
                self.rules,
                self.host,
                self.rule_errors,
                demo=self.demo,
            )
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._show_error, exc)
            return
        self.call_from_thread(self._update_report, report)

    def _show_error(self, exc: Exception) -> None:
        self.query_one("#status", Static).update(Text(f"Erreur : {exc}", style="bold red"))
        self.notify(f"Erreur de collecte : {exc}", severity="error")

    def _merge_history(self, report: HealthReport) -> HealthReport:
        now = datetime.now()
        ttl = self.config.finding_ttl_seconds
        merged: dict[str, Finding] = {}
        for finding in self.history.values():
            if finding.last_seen and (now - finding.last_seen).total_seconds() < ttl:
                merged[finding.fingerprint] = finding
        for finding in report.findings:
            finding.last_seen = now
            merged[finding.fingerprint] = finding
        report.findings = sorted(
            merged.values(),
            key=lambda f: (SEVERITY_ORDER[f.severity], f.count),
            reverse=True,
        )
        report.score = score_findings(report.findings)
        report.verdict = verdict_for(report.score)
        self.history = merged
        return report

    def _update_report(self, report: HealthReport) -> None:
        report = self._merge_history(report)
        self.last_report = report
        self.sub_title = f"{report.host} · {report.score}/100"
        self._render_summary(report)
        self._render_findings(report)
        self._render_metrics(report)
        self._render_logs(report)
        self.query_one("#doctor", Static).update(Text(doctor_text(report, self.simplicity, self.verbosity)))
        self._update_status(report)
        if report.findings:
            self._show_finding_detail(report.findings[0])
        else:
            self._current_finding = None

    def _render_summary(self, report: HealthReport) -> None:
        text = Text()
        text.append("🩺 ", style="bold")
        text.append(f"{report.score}/100", style="bold")
        text.append(f" — {report.verdict}\n", style="bold")
        text.append(health_bar(report.score), style="green" if report.score >= 75 else "yellow" if report.score >= 50 else "red")
        text.append("\n")
        text.append(vitals_line(report))
        self.query_one("#summary", Static).update(text)

    def _render_findings(self, report: HealthReport) -> None:
        table = self.query_one("#findings", DataTable)
        table.clear(columns=False)
        self._finding_map = {}
        findings = report.findings
        if self.verbosity == "quiet":
            findings = findings[:1]
        elif self.verbosity == "normal":
            findings = [f for f in findings if f.severity != "info"][:10]
        for index, finding in enumerate(findings):
            text = finding.text(self.simplicity)
            if finding.count > 1:
                text += f"  (×{finding.count})"
            key = str(index)
            self._finding_map[key] = finding
            table.add_row(
                Text(SEVERITY_LABEL.get(finding.severity, finding.severity.upper()), style=SEVERITY_STYLE.get(finding.severity, "")),
                Text(finding.area, style="dim"),
                Text(text),
                Text(finding.timestamp or "—", style="dim"),
                key=key,
            )

    def _render_metrics(self, report: HealthReport) -> None:
        table = self.query_one("#metrics", DataTable)
        table.clear(columns=False)
        metrics = report.metrics
        if self.verbosity == "quiet":
            metrics = [m for m in metrics if m.key in ("cpu", "mem", "disk:/")]
        elif self.verbosity == "normal":
            metrics = [m for m in metrics if m.status != "ok" or m.key in ("cpu", "mem", "load", "disk:/")]
        for metric in metrics:
            table.add_row(
                Text(metric.label),
                Text(metric.display()),
                Text(metric.status.upper(), style=STATUS_STYLE.get(metric.status, "")),
                Text(metric.detail, style="dim"),
            )

    def _render_logs(self, report: HealthReport) -> None:
        log = self.query_one("#logs", RichLog)
        log.clear()
        if self.verbosity not in ("verbose", "debug"):
            return
        limit = 40 if self.verbosity == "debug" else 15
        for line in report.logs[-limit:]:
            text = Text()
            if line.timestamp:
                text.append(line.timestamp + " ", style="dim")
            text.append(line.source + ": ", style="dim cyan")
            text.append(line.message[:300], style=SEVERITY_STYLE.get(line.severity, ""))
            log.write(text)

    def _update_status(self, report: HealthReport) -> None:
        actions = (
            "r rafraîchir · a analyser · v verbosité · s simplicité · p pause · "
            "m hôte · t term/ssh · c commande · q quitter"
        )
        status = (
            f"Hôte: {report.host} ({report.host_type}) · "
            f"V:{self.verbosity} · S:{self.simplicity} · "
            f"{report.stats.get('logs', 0)} logs · {report.stats.get('findings', 0)} constats · "
            f"{actions}"
        )
        if self.paused:
            status = "PAUSE · " + status
        self.query_one("#status", Static).update(Text(status, style="dim"))

    def _show_finding_detail(self, finding: Finding) -> None:
        self._current_finding = finding
        lines = [
            finding.title,
            "",
            finding.text(self.simplicity),
        ]
        if finding.advice:
            lines += ["", f"Conseil : {finding.advice}"]
        if finding.commands:
            lines += ["", "Commandes :"] + [f"  {c}" for c in finding.commands]
        if finding.evidence:
            lines += ["", "Preuves :"] + [f"  {e}" for e in finding.evidence[:4]]
        self.query_one("#finding-detail", Static).update(Text("\n".join(lines), style="dim"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "findings":
            return
        key = getattr(event.row_key, "value", str(event.row_key))
        finding = self._finding_map.get(str(key))
        if finding:
            self._show_finding_detail(finding)

    def action_refresh(self) -> None:
        self.refresh_report()

    def action_analyze(self) -> None:
        self.paused = False
        self.refresh_report()

    def action_cycle_verbosity(self) -> None:
        index = VERBOSITIES.index(self.verbosity) if self.verbosity in VERBOSITIES else 1
        self.verbosity = VERBOSITIES[(index + 1) % len(VERBOSITIES)]
        if self.last_report:
            self._update_report(self.last_report)
        self.notify(f"Niveau de verbosité : {self.verbosity}")

    def action_cycle_simplicity(self) -> None:
        index = SIMPLICITIES.index(self.simplicity) if self.simplicity in SIMPLICITIES else 1
        self.simplicity = SIMPLICITIES[(index + 1) % len(SIMPLICITIES)]
        if self.last_report:
            self._update_report(self.last_report)
        self.notify(f"Simplicité : {self.simplicity}")

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.last_report:
            self._update_status(self.last_report)
        self.notify("En pause" if self.paused else "Reprise")
        if not self.paused:
            self.refresh_report()

    def action_cycle_host(self) -> None:
        if self.demo:
            self.notify("Hôte de démonstration")
            return
        if len(self.host_names) <= 1:
            self.notify("Aucun autre hôte configuré")
            return
        self.host_index = (self.host_index + 1) % len(self.host_names)
        name = self.host_names[self.host_index]
        try:
            self.host = self.config.host(name)
        except KeyError as exc:
            self.notify(str(exc), severity="error")
            return
        self._current_finding = None
        self.notify(f"Hôte : {name}")
        self.refresh_report()

    def _open_terminal(self) -> bool:
        if self.demo:
            self.notify("Aucun terminal pour l'hôte de démonstration", severity="warning")
            return False
        try:
            if in_tmux():
                pane = open_pane(self.host, self._term_panes.get(self.host.name))
                self._term_panes[self.host.name] = pane
            else:
                with self.suspend():
                    run_interactive(self.host)
                self.refresh_report()
        except TerminalError as exc:
            self.notify(f"Terminal : {exc}", severity="error")
            return False
        return True

    def action_terminal(self) -> None:
        if self._open_terminal() and in_tmux():
            self.notify(f"Terminal ouvert : {self.host.name}")

    def action_send_command(self) -> None:
        finding = self._current_finding
        if not finding or not finding.commands:
            self.notify("Aucune commande pour ce constat", severity="warning")
            return
        if not in_tmux():
            self.notify(
                "L'envoi de commande nécessite tmux (utilisez t pour le terminal)",
                severity="warning",
            )
            return
        pane = self._term_panes.get(self.host.name, "")
        if not pane_alive(pane):
            self._term_panes.pop(self.host.name, None)
            if not self._open_terminal():
                return
            self.notify(
                "Terminal ouvert : connectez-vous, puis appuyez à nouveau sur c"
            )
            return
        try:
            send_literal(pane, " ; ".join(finding.commands))
        except TerminalError as exc:
            self._term_panes.pop(self.host.name, None)
            self.notify(f"Terminal : {exc}", severity="error")
            return
        self.notify("Commande tapée dans le terminal — relisez puis Entrée")

    def action_help(self) -> None:
        self.query_one(TabbedContent).active = "tab-help"

    def action_quit(self) -> None:
        self.exit()
