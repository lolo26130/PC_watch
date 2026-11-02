"""Chargement et application des règles de diagnostic."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from .models import Finding, LogLine, SEVERITY_ORDER, normalize_severity


@dataclass
class Rule:
    id: str
    area: str
    severity: str
    pattern: str
    title: str
    simple: str = ""
    normal: str = ""
    expert: str = ""
    advice: str = ""
    commands: list[str] = field(default_factory=list)
    regex: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    def compile(self) -> None:
        self.severity = normalize_severity(self.severity)
        self.regex = re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)


def load_rules(path: str | Path, local_path: str | Path | None = None) -> tuple[list[Rule], list[str]]:
    """Charge rules.toml et éventuellement un fichier local qui surcharge les ids."""

    errors: list[str] = []
    rules: dict[str, Rule] = {}
    path = Path(path)
    if not path.is_file():
        return [], [f"fichier de règles introuvable: {path}"]

    def load_file(file_path: Path, override: bool) -> None:
        try:
            with file_path.open("rb") as f:
                data = tomllib.load(f)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")
            return
        raw_rules = data.get("rules", [])
        if not isinstance(raw_rules, list):
            errors.append(f"{file_path}: 'rules' doit être une liste")
            return
        for item in raw_rules:
            if not isinstance(item, dict):
                errors.append(f"{file_path}: règle invalide ignorée")
                continue
            try:
                rule = Rule(
                    id=str(item["id"]),
                    area=str(item.get("area", "custom")),
                    severity=str(item.get("severity", "warning")),
                    pattern=str(item["pattern"]),
                    title=str(item.get("title", item["id"])),
                    simple=str(item.get("simple", "")),
                    normal=str(item.get("normal", "")),
                    expert=str(item.get("expert", "")),
                    advice=str(item.get("advice", "")),
                    commands=[str(c) for c in item.get("commands", [])],
                )
                rule.compile()
            except KeyError as exc:
                errors.append(f"{file_path}: champ manquant {exc} dans une règle")
                continue
            except re.error as exc:
                errors.append(f"{file_path}: regex invalide pour {item.get('id', '?')}: {exc}")
                continue
            if not override and rule.id in rules:
                errors.append(f"{file_path}: règle dupliquée {rule.id}, ignorée")
                continue
            rules[rule.id] = rule

    load_file(path, override=False)
    if local_path:
        local_path = Path(local_path)
        if local_path.is_file():
            load_file(local_path, override=True)
    return list(rules.values()), errors


def guess_severity(text: str) -> str:
    lowered = text.lower()
    if any(
        word in lowered
        for word in (
            "kernel panic",
            "panic",
            "oops",
            "general protection fault",
            "i/o error",
            "buffer i/o error",
            "critical medium error",
            "out of memory",
            "oom-kill",
            "uncorrectable",
            "machine check",
            "mce",
            "segfault",
        )
    ):
        return "critical"
    if any(
        word in lowered
        for word in (
            "error",
            "failed",
            "failure",
            "warning",
            "warn",
            "denied",
            "timeout",
            "timed out",
            "reset",
            "throttl",
            "degraded",
            "refused",
        )
    ):
        return "warning"
    return "info"


def match_logs(logs: Iterable[LogLine], rules: Iterable[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    logs = list(logs)
    for rule in rules:
        if rule.regex is None:
            continue
        matches: list[LogLine] = []
        for line in logs:
            text = line.message or line.raw
            if text and rule.regex.search(text):
                matches.append(line)
        if not matches:
            continue
        evidence: list[str] = []
        sources: list[str] = []
        for line in matches[-5:]:
            snippet = (line.message or line.raw).strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:237] + "..."
            if snippet not in evidence:
                evidence.append(snippet)
            if line.source and line.source not in sources:
                sources.append(line.source)
        latest = matches[-1]
        digest = hashlib.sha1(
            "|".join(sorted(evidence)).encode("utf-8", "replace")
        ).hexdigest()[:12]
        findings.append(
            Finding(
                id=rule.id,
                area=rule.area,
                severity=rule.severity,
                title=rule.title,
                detail=f"{len(matches)} occurrence(s) détectée(s)",
                simple=rule.simple,
                normal=rule.normal,
                expert=rule.expert,
                advice=rule.advice,
                commands=rule.commands,
                source=", ".join(sources) or latest.source,
                timestamp=latest.timestamp,
                count=len(matches),
                evidence=evidence,
                fingerprint=f"{rule.id}:{digest}",
            )
        )
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.count), reverse=True)
    return findings


def dedupe_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Fusionne les doublons par fingerprint, en gardant le plus récent."""

    merged: dict[str, Finding] = {}
    for finding in findings:
        key = finding.fingerprint or finding.id
        if key not in merged:
            merged[key] = finding
            continue
        current = merged[key]
        current.count += finding.count
        current.timestamp = max(current.timestamp, finding.timestamp)
        for item in finding.evidence:
            if item not in current.evidence and len(current.evidence) < 8:
                current.evidence.append(item)
        if SEVERITY_ORDER[finding.severity] > SEVERITY_ORDER[current.severity]:
            current.severity = finding.severity
    result = list(merged.values())
    result.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.count), reverse=True)
    return result


def score_findings(findings: Iterable[Finding]) -> int:
    weights = {"critical": 25, "warning": 8, "info": 2}
    unique = {f.fingerprint or f.id: f for f in findings}
    penalty = sum(weights.get(f.severity, 0) for f in unique.values())
    return max(0, min(100, 100 - penalty))


def verdict_for(score: int) -> str:
    if score >= 95:
        return "Excellent état général"
    if score >= 80:
        return "Bonne santé, quelques signes à surveiller"
    if score >= 60:
        return "État fragile, quelques symptômes"
    if score >= 35:
        return "Santé dégradée, action recommandée"
    return "État critique, intervention urgente"
