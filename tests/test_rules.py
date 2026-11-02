from pathlib import Path

from pcwatch_lib.models import LogLine
from pcwatch_lib.rules import (
    dedupe_findings,
    load_rules,
    match_logs,
    score_findings,
    verdict_for,
)

ROOT = Path(__file__).resolve().parent.parent


def _rules():
    rules, errors = load_rules(ROOT / "rules.toml")
    assert not errors, errors
    assert len(rules) >= 20
    return rules


def test_disk_io_error():
    rules = _rules()
    logs = [
        LogLine(
            timestamp="2026-11-02T10:00:00",
            source="journal:kernel",
            message="nvme0n1: I/O error, dev nvme0n1, sector 42",
            severity="critical",
        )
    ]
    findings = match_logs(logs, rules)
    assert any(f.id == "kernel_io_error" for f in findings)
    assert any(f.severity == "critical" for f in findings)


def test_oom():
    findings = match_logs(
        [LogLine(message="Out of memory: Killed process 123 (firefox)")],
        _rules(),
    )
    assert any(f.id == "oom_killer" for f in findings)


def test_service_and_auth():
    logs = [
        LogLine(message="Failed to start motd-news.service - Message of the Day."),
        LogLine(message="Failed password for invalid user admin from 203.0.113.7"),
        LogLine(message="wlan0: link is down"),
    ]
    ids = {f.id for f in match_logs(logs, _rules())}
    assert "systemd_failed" in ids
    assert "auth_failed" in ids
    assert "link_down" in ids


def test_score_and_verdict():
    findings = match_logs(
        [LogLine(message="kernel panic - not syncing")],
        _rules(),
    )
    assert score_findings(findings) < 100
    assert verdict_for(100) == "Excellent état général"


def test_dedupe():
    findings = match_logs(
        [LogLine(message="I/O error, dev nvme0n1")],
        _rules(),
    )
    merged = dedupe_findings(findings + findings)
    by_id = {f.id: f for f in merged}
    assert by_id["kernel_io_error"].count >= 2
