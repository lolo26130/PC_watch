import json
from pathlib import Path

from pcwatch_lib.analyzer import collect_and_analyze
from pcwatch_lib.config import load_config
from pcwatch_lib.doctor import doctor_text, health_bar
from pcwatch_lib.report import report_json
from pcwatch_lib.rules import load_rules

ROOT = Path(__file__).resolve().parent.parent


def test_demo_report():
    config = load_config("/tmp/pcwatch-missing.toml")
    rules, errors = load_rules(ROOT / "rules.toml")
    assert not errors
    report = collect_and_analyze(
        config,
        rules,
        config.host("local"),
        errors,
        demo=True,
    )
    assert report.host == "demo-pc"
    assert report.findings
    assert report.score < 100
    assert report.max_severity() == "critical"
    assert report.exit_code() == 2
    assert len(health_bar(report.score)) == 20

    data = json.loads(report_json(report))
    assert data["host"] == "demo-pc"
    assert data["findings"]
    assert data["score"] == report.score


def test_doctor_levels():
    config = load_config("/tmp/pcwatch-missing.toml")
    rules, _ = load_rules(ROOT / "rules.toml")
    report = collect_and_analyze(config, rules, config.host("local"), demo=True)
    simple = doctor_text(report, "simple", "normal")
    expert = doctor_text(report, "expert", "debug")
    assert "Dr. PC" in simple
    assert "Dr. PC" in expert
    assert "Symptômes" in expert
