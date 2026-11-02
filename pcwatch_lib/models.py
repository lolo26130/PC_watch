"""Modèles de données de PC Watch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
SEVERITY_LABEL = {"info": "INFO", "warning": "WARN", "critical": "CRIT"}
SEVERITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def normalize_severity(value: str) -> str:
    value = (value or "info").lower()
    if value in ("crit", "critical", "fatal", "emerg", "alert"):
        return "critical"
    if value in ("warn", "warning", "error", "err"):
        return "warning"
    return "info"


@dataclass
class LogLine:
    """Une ligne de log importante, normalisée."""

    timestamp: str = ""
    source: str = ""
    message: str = ""
    raw: str = ""
    severity: str = "info"

    def __post_init__(self) -> None:
        self.severity = normalize_severity(self.severity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class Metric:
    """Une mesure (constante vitale) du système."""

    key: str
    label: str
    value: float | int | str
    unit: str = ""
    status: str = "ok"  # ok | info | warning | critical
    detail: str = ""

    def __post_init__(self) -> None:
        self.status = normalize_severity(self.status) if self.status != "ok" else "ok"

    def display(self) -> str:
        if isinstance(self.value, float):
            value = f"{self.value:.1f}"
        else:
            value = str(self.value)
        return f"{value}{self.unit}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class Finding:
    """Un symptôme détecté et son interprétation."""

    id: str
    area: str
    severity: str
    title: str
    detail: str = ""
    simple: str = ""
    normal: str = ""
    expert: str = ""
    advice: str = ""
    commands: list[str] = field(default_factory=list)
    source: str = ""
    timestamp: str = ""
    count: int = 1
    evidence: list[str] = field(default_factory=list)
    fingerprint: str = ""
    last_seen: Optional[datetime] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.severity = normalize_severity(self.severity)
        if not self.fingerprint:
            self.fingerprint = f"{self.id}:{self.title}"

    def text(self, simplicity: str = "normal") -> str:
        simplicity = (simplicity or "normal").lower()
        if simplicity == "simple" and self.simple:
            return self.simple
        if simplicity == "expert" and self.expert:
            return self.expert
        return self.normal or self.detail or self.title

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "area": self.area,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "simple": self.simple,
            "normal": self.normal,
            "expert": self.expert,
            "advice": self.advice,
            "commands": self.commands,
            "source": self.source,
            "timestamp": self.timestamp,
            "count": self.count,
            "evidence": self.evidence,
            "fingerprint": self.fingerprint,
        }


@dataclass
class FailedUnit:
    unit: str
    load: str = ""
    active: str = ""
    sub: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "load": self.load,
            "active": self.active,
            "sub": self.sub,
            "description": self.description,
        }


@dataclass
class Collected:
    """Données brutes collectées sur une machine (locale ou SSH)."""

    host: str = "local"
    host_type: str = "local"
    logs: list[LogLine] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    failed_units: list[FailedUnit] = field(default_factory=list)
    smart: dict[str, dict[str, Any]] = field(default_factory=dict)
    sensors: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    raw_sections: dict[str, str] = field(default_factory=dict)
    collected_at: str = ""

    def __post_init__(self) -> None:
        if not self.collected_at:
            self.collected_at = datetime.now().isoformat(timespec="seconds")


@dataclass
class HealthReport:
    """Résultat de l'analyse, prêt à afficher."""

    host: str
    host_type: str
    generated_at: str
    score: int
    verdict: str
    findings: list[Finding]
    metrics: list[Metric]
    logs: list[LogLine]
    errors: list[str]
    stats: dict[str, Any]
    failed_units: list[FailedUnit]
    collected_at: str = ""

    def max_severity(self) -> str:
        if not self.findings:
            return "info"
        return max(self.findings, key=lambda f: SEVERITY_ORDER[f.severity]).severity

    def exit_code(self) -> int:
        severity = self.max_severity()
        return {"info": 0, "warning": 1, "critical": 2}[severity]

    def top_findings(self, limit: int = 5) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.count),
            reverse=True,
        )[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "host_type": self.host_type,
            "generated_at": self.generated_at,
            "collected_at": self.collected_at,
            "score": self.score,
            "verdict": self.verdict,
            "max_severity": self.max_severity(),
            "findings": [f.to_dict() for f in self.findings],
            "metrics": [m.to_dict() for m in self.metrics],
            "logs": [l.to_dict() for l in self.logs],
            "errors": self.errors,
            "stats": self.stats,
            "failed_units": [u.to_dict() for u in self.failed_units],
        }
