from pathlib import Path

import pcwatch_lan
from pcwatch_lib.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def test_build_command_config_host():
    config = load_config(ROOT / "config.example.toml")
    cmd = pcwatch_lan.build_command(
        "/usr/local/bin/pcwatch",
        config,
        "local",
        interval=60,
        verbosity="verbose",
        simplicity="expert",
    )
    assert cmd == [
        "/usr/local/bin/pcwatch",
        "--host",
        "local",
        "--interval",
        "60",
        "--verbosity",
        "verbose",
        "--simplicity",
        "expert",
    ]


def test_build_command_ssh_alias():
    config = load_config("/tmp/pcwatch-missing-lan.toml")
    cmd = pcwatch_lan.build_command(
        "/usr/local/bin/pcwatch",
        config,
        "pi1_emule_300GB_HD",
        interval=None,
        verbosity=None,
        simplicity=None,
    )
    assert cmd == ["/usr/local/bin/pcwatch", "--ssh", "pi1_emule_300GB_HD"]


def test_sanitize_window_unique():
    used: set[str] = set()
    assert pcwatch_lan.sanitize_window("local", used) == "local"
    assert pcwatch_lan.sanitize_window("local", used) == "local-2"
    assert pcwatch_lan.sanitize_window("user@192.168.1.4", used) == "user_192.168.1.4"


def test_resolve_hosts_from_monitor():
    config = load_config(ROOT / "config.example.toml")
    hosts = pcwatch_lan.resolve_hosts(config, [], None, all_ssh=False)
    assert hosts == ["local", "raspberrypi"]


def test_resolve_hosts_explicit():
    config = load_config("/tmp/pcwatch-missing-lan.toml")
    hosts = pcwatch_lan.resolve_hosts(
        config,
        ["local"],
        "pi1_emule_300GB_HD,piscreen",
        all_ssh=False,
    )
    assert hosts == ["local", "pi1_emule_300GB_HD", "piscreen"]


def test_list_cli(capsys):
    rc = pcwatch_lan.main(
        [
            "--config",
            "/tmp/pcwatch-missing-lan.toml",
            "--list",
            "--hosts",
            "local,pi1_emule_300GB_HD",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "session:" in captured.out
    assert "--host local" in captured.out
    assert "--ssh pi1_emule_300GB_HD" in captured.out
