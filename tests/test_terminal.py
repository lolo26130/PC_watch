from dataclasses import dataclass

from pcwatch_lib import terminal
from pcwatch_lib.config import HostConfig


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def test_ssh_argv_local(monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    assert terminal.ssh_argv(HostConfig("local", type="local")) == ["/usr/bin/zsh"]


def test_ssh_argv_ssh_options():
    host = HostConfig(
        "pi",
        type="ssh",
        target="pi@rpi",
        port=2222,
        identity="/home/u/.ssh/id_ed25519",
        ssh_options=["-o", "Compression=yes"],
    )
    assert terminal.ssh_argv(host) == [
        "ssh",
        "-i",
        "/home/u/.ssh/id_ed25519",
        "-p",
        "2222",
        "-o",
        "Compression=yes",
        "pi@rpi",
    ]


def test_ssh_argv_ssh_without_target():
    assert terminal.ssh_argv(HostConfig("pi", type="ssh")) is None


def test_ssh_argv_demo():
    assert terminal.ssh_argv(HostConfig("demo-pc", type="demo")) is None


def test_open_pane_reuses_existing(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    pane = terminal.open_pane(HostConfig("local", type="local"), existing="%3")
    assert pane == "%3"
    assert calls[0][:3] == ["tmux", "display-message", "-p"]
    assert calls[1][:3] == ["tmux", "select-pane", "-t"]


def test_open_pane_splits(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%0")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "split-window":
            return FakeProc(stdout="%7\n")
        return FakeProc()

    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    host = HostConfig("pi", type="ssh", target="pi@rpi")
    pane = terminal.open_pane(host)
    assert pane == "%7"
    split = calls[0]
    assert split[1] == "split-window"
    assert "-t" in split and "%0" in split
    assert split[-1] == "ssh pi@rpi"
    # titre du panneau
    assert calls[1][1] == "select-pane"


def test_send_literal(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    terminal.send_literal("%4", "journalctl -k -p warning")
    assert calls[0][:3] == ["tmux", "display-message", "-p"]
    send = calls[1]
    assert send[1] == "send-keys"
    assert "-l" in send
    assert send[-1] == "journalctl -k -p warning"


def test_pane_alive_missing():
    assert terminal.pane_alive("") is False
