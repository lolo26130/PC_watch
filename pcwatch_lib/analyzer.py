"""Analyse : logs + métriques + services -> rapport de santé."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .config import Config, HostConfig
from .models import (
    Collected,
    Finding,
    HealthReport,
    Metric,
    SEVERITY_ORDER,
)
from .rules import (
    Rule,
    dedupe_findings,
    match_logs,
    score_findings,
    verdict_for,
)


def _metric_finding(metric: Metric, host: str) -> Finding | None:
    if metric.status not in ("warning", "critical"):
        return None
    key = metric.key
    area = key.split(":", 1)[0]
    value = metric.display()
    detail = metric.detail
    title = metric.label
    simple = normal = expert = ""
    advice = ""
    commands: list[str] = []

    if area == "disk":
        mount = key.split(":", 1)[1] if ":" in key else metric.label
        title = f"Disque {mount} très rempli"
        simple = f"Le disque {mount} est rempli à {value}."
        normal = (
            f"Le disque {mount} est utilisé à {value}. Il reste peu de place ; "
            "les écritures et les mises à jour peuvent échouer."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Libérez de l'espace ou déplacez des données vers un autre disque."
        commands = [
            f"df -h {mount}",
            f"du -xhd1 {mount} 2>/dev/null | sort -h | tail -20",
        ]
    elif area == "mem":
        title = "Mémoire vive très sollicitée"
        simple = f"La mémoire est utilisée à {value}."
        normal = (
            f"La mémoire vive est utilisée à {value}. Le système peut commencer "
            "à swapper et ralentir."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Fermez les applications gourmandes ou ajoutez de la mémoire."
        commands = ["free -h", "ps aux --sort=-%mem | head -10"]
    elif area == "swap":
        title = "Swap fortement utilisé"
        simple = f"Le swap est utilisé à {value}."
        normal = (
            f"Le swap est utilisé à {value}. Cela peut indiquer une pression mémoire "
            "ou un manque de RAM."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Surveillez la mémoire ; le swap sur disque est lent."
        commands = ["free -h", "swapon --show", "ps aux --sort=-%mem | head -10"]
    elif area == "load":
        title = "Charge système élevée"
        simple = f"Le processeur est très chargé (charge {value})."
        normal = (
            f"La charge système est de {value}. Les processus attendent peut-être "
            "des ressources CPU ou disque."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Identifiez les processus gourmands et vérifiez les I/O."
        commands = ["uptime", "ps aux --sort=-%cpu | head -10", "vmstat 1 5"]
    elif area == "cpu":
        title = "CPU très sollicité"
        simple = f"Le CPU est utilisé à {value}."
        normal = f"L'utilisation CPU atteint {value}. Vérifiez les processus actifs."
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Identifiez le processus qui consomme le plus de CPU."
        commands = ["top -b -n1 | head -15", "ps aux --sort=-%cpu | head -10"]
    elif area == "temp":
        title = "Température élevée"
        simple = f"Un capteur chauffe : {value}."
        normal = (
            f"La température {metric.label} atteint {value}. Une surchauffe peut "
            "provoquer du throttling ou des arrêts."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Vérifiez la ventilation, la poussière et les ventilateurs."
        commands = ["sensors", "ps aux --sort=-%cpu | head -10"]
    elif area == "smart":
        parts = key.split(":")
        dev = parts[1] if len(parts) > 1 else "?"
        attr = parts[2] if len(parts) > 2 else ""
        title_map = {
            "pending": "Secteurs en attente dans le disque",
            "reallocated": "Secteurs réalloués dans le disque",
            "uncorrectable": "Secteurs non corrigeables dans le disque",
            "media_errors": "Erreurs d'intégrité média",
            "critical_warning": "Alerte critique SMART",
            "available_spare": "Réserve de blocs faible",
            "temp": "Température du disque élevée",
            "used": "Usure du disque avancée",
        }
        title = f"{title_map.get(attr, 'Alerte SMART')} ({dev})"
        simple_map = {
            "pending": f"Le disque {dev} a des secteurs instables.",
            "reallocated": f"Le disque {dev} a déjà réalloué des secteurs.",
            "uncorrectable": f"Le disque {dev} a des secteurs illisibles.",
            "media_errors": f"Le disque {dev} signale des erreurs de données.",
            "critical_warning": f"Le disque {dev} est en alerte critique.",
            "available_spare": f"Le disque {dev} manque de réserve.",
            "temp": f"Le disque {dev} chauffe ({value}).",
            "used": f"Le disque {dev} est usé à {value}.",
        }
        simple = simple_map.get(attr, f"Le disque {dev} montre un signe d'usure.")
        normal = (
            f"SMART signale « {metric.label} » sur {dev} : {value}. "
            "Un disque peut encore fonctionner, mais le risque de perte de données augmente."
        )
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Sauvegardez les données importantes et surveillez l'évolution SMART."
        commands = [f"sudo smartctl -a {dev}", "journalctl -k -p warning -b"]
    else:
        title = metric.label
        simple = f"{metric.label} : {value}."
        normal = f"{metric.label} : {value}. {detail}"
        expert = f"{metric.label} : {value} — {detail}"
        advice = "Surveillez cette valeur."
        commands = []

    return Finding(
        id=f"metric:{key}",
        area=area,
        severity=metric.status,
        title=title,
        detail=detail,
        simple=simple,
        normal=normal,
        expert=expert,
        advice=advice,
        commands=commands,
        source=host,
        timestamp="",
        count=1,
        evidence=[f"{metric.label}: {value}" + (f" ({detail})" if detail else "")],
        fingerprint=f"metric:{key}",
    )


def metric_findings(collected: Collected) -> list[Finding]:
    findings: list[Finding] = []
    for metric in collected.metrics:
        if metric.key == "failed_units":
            continue
        finding = _metric_finding(metric, collected.host)
        if finding:
            findings.append(finding)
    return findings


def failed_units_finding(collected: Collected) -> Finding | None:
    if not collected.failed_units:
        return None
    units = [u.unit for u in collected.failed_units]
    evidence = [
        f"{u.unit}: {u.active}/{u.sub}" + (f" — {u.description}" if u.description else "")
        for u in collected.failed_units[:8]
    ]
    return Finding(
        id="failed_units",
        area="services",
        severity="warning",
        title="Services systemd en échec",
        detail=f"{len(units)} service(s) en échec",
        simple=f"{len(units)} service(s) système ne démarrent pas correctement.",
        normal=(
            f"{len(units)} service(s) systemd sont en échec : {', '.join(units[:5])}. "
            "Ils peuvent être secondaires, mais il faut vérifier."
        ),
        expert="Unités en échec : " + ", ".join(units),
        advice="Inspectez les services concernés et leurs journaux.",
        commands=[f"systemctl status {units[0]}", f"journalctl -u {units[0]} -b"],
        source=collected.host,
        count=len(units),
        evidence=evidence,
        fingerprint="failed_units",
    )


def collect_and_analyze(
    config: Config,
    rules: Iterable[Rule],
    host: HostConfig,
    rule_errors: list[str] | None = None,
    demo: bool = False,
) -> HealthReport:
    if demo:
        from .demo import demo_collected

        collected = demo_collected()
    elif host.is_ssh:
        from .remote import collect_remote

        collected = collect_remote(config, host)
    else:
        from .collectors import collect_local

        collected = collect_local(config, host.name)

    findings: list[Finding] = []
    findings.extend(match_logs(collected.logs, rules))
    findings.extend(metric_findings(collected))
    failed = failed_units_finding(collected)
    if failed:
        findings.append(failed)
    if collected.errors and not collected.logs and not collected.metrics:
        target = getattr(host, "target", "") or collected.host
        findings.append(
            Finding(
                id="collect_error",
                area="collect",
                severity="warning",
                title="Collecte impossible",
                detail="Aucune donnée exploitable",
                simple="Je n'ai pas pu lire les données de cette machine.",
                normal=(
                    "La collecte n'a retourné ni journal ni métrique. "
                    "La machine est peut-être injoignable ou les permissions manquent."
                ),
                expert="\n".join(collected.errors),
                advice="Vérifiez la connexion SSH, la clé et les permissions de lecture.",
                commands=[f"ssh {target} true", f"ssh {target} 'journalctl -n 5 --no-pager'"],
                source=collected.host,
                count=1,
                evidence=collected.errors[:5],
                fingerprint="collect_error",
            )
        )
    findings = dedupe_findings(findings)

    score = score_findings(findings)
    verdict = verdict_for(score)
    errors = list(collected.errors)
    errors.extend(config.warnings)
    errors.extend(rule_errors or [])

    stats: dict[str, Any] = {
        "logs": len(collected.logs),
        "metrics": len(collected.metrics),
        "findings": len(findings),
        "critical": sum(1 for f in findings if f.severity == "critical"),
        "warning": sum(1 for f in findings if f.severity == "warning"),
        "info": sum(1 for f in findings if f.severity == "info"),
        "failed_units": len(collected.failed_units),
        "smart_devices": len(collected.smart),
        "host_meta": collected.meta,
        "config_path": str(config.path),
        "rules_path": str(config.rules_path),
    }
    return HealthReport(
        host=collected.host,
        host_type=collected.host_type,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        score=score,
        verdict=verdict,
        findings=sorted(
            findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.count),
            reverse=True,
        ),
        metrics=collected.metrics,
        logs=collected.logs,
        errors=errors,
        stats=stats,
        failed_units=collected.failed_units,
        collected_at=collected.collected_at,
    )
