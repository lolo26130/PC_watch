from pathlib import Path

from pcwatch_lib.config import adhoc_ssh_host, load_config


def test_defaults_without_file(tmp_path):
    config = load_config(tmp_path / "missing.toml")
    assert config.refresh_seconds == 30
    assert "local" in config.hosts
    assert config.rules_path.name == "rules.toml"
    assert config.verbosity in ("normal", "verbose", "debug", "quiet")


def test_user_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
refresh_seconds = 7
verbosity = "verbose"
simplicity = "expert"

[thresholds]
disk_warn_percent = 70

[hosts.raspberrypi]
type = "ssh"
target = "pi@example.local"
port = 2222
identity = "~/.ssh/id_ed25519"

[monitor]
session = "pclan"
interval = 45
hosts = ["local", "raspberrypi"]
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.refresh_seconds == 7
    assert config.verbosity == "verbose"
    assert config.simplicity == "expert"
    assert config.thresholds_for("disk_warn_percent", 85) == 70
    host = config.host("raspberrypi")
    assert host.type == "ssh"
    assert host.target == "pi@example.local"
    assert host.port == 2222
    assert config.monitor["session"] == "pclan"
    assert config.monitor["interval"] == 45
    assert config.monitor["hosts"] == ["local", "raspberrypi"]


def test_adhoc_ssh_host():
    host = adhoc_ssh_host("pi@rpi", port=2200, identity="~/.ssh/id_ed25519")
    assert host.is_ssh
    assert host.port == 2200
    assert host.target == "pi@rpi"
    assert host.identity.endswith(".ssh/id_ed25519")
