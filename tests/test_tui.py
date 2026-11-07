import asyncio

from pcwatch_lib import tui as tui_module
from pcwatch_lib.config import HostConfig, load_config
from pcwatch_lib.models import Finding
from pcwatch_lib.tui import CommandPicker, PCWatchApp


def _finding(*commands: str) -> Finding:
    return Finding(
        id="test",
        area="test",
        severity="warning",
        title="Constat de test",
        commands=list(commands),
    )


def _app(monkeypatch, sent: list[str]) -> PCWatchApp:
    config = load_config("/tmp/pcwatch-missing-tui.toml")
    app = PCWatchApp(config, [], HostConfig("local", type="local"))
    app.paused = True  # pas de collecte pendant le test
    monkeypatch.setattr(tui_module, "in_tmux", lambda: True)
    monkeypatch.setattr(tui_module, "pane_alive", lambda pane: pane == "%1")
    monkeypatch.setattr(tui_module, "open_pane", lambda host, existing=None: "%1")
    monkeypatch.setattr(tui_module, "send_literal", lambda pane, text: sent.append(text))
    app._term_panes["local"] = "%1"
    return app


def test_c_sends_only_the_chosen_command(monkeypatch):
    sent: list[str] = []
    app = _app(monkeypatch, sent)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._current_finding = _finding(
                "df -h", "du -xhd1 /", "smartctl -a /dev/sda"
            )
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, CommandPicker)
            await pilot.press("2")
            await pilot.pause()
            assert sent == ["du -xhd1 /"]

    asyncio.run(run())


def test_picker_arrow_and_enter(monkeypatch):
    sent: list[str] = []
    app = _app(monkeypatch, sent)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._current_finding = _finding("df -h", "free -h")
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert sent == ["free -h"]

    asyncio.run(run())


def test_picker_escape_cancels(monkeypatch):
    sent: list[str] = []
    app = _app(monkeypatch, sent)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._current_finding = _finding("df -h", "free -h")
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, CommandPicker)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, CommandPicker)
            assert sent == []

    asyncio.run(run())


def test_single_command_sent_directly(monkeypatch):
    sent: list[str] = []
    app = _app(monkeypatch, sent)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._current_finding = _finding("df -h")
            await pilot.press("c")
            await pilot.pause()
            assert sent == ["df -h"]

    asyncio.run(run())
