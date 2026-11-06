#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Lance une session tmux avec un pcwatch TUI par machine.

Par défaut, lit [monitor].hosts dans ~/.config/pc_watch/config.toml.
Les noms inconnus de [hosts.*] sont passés à `pcwatch --ssh`.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from pcwatch_lib.config import (  # noqa: E402
    SIMPLICITIES,
    VERBOSITIES,
    Config,
    load_config,
)

DEFAULT_SESSION = "pcwatch"


def pcwatch_executable() -> str:
    found = shutil.which("pcwatch")
    if found:
        return found
    local = Path(__file__).resolve().with_name("pcwatch.py")
    if local.is_file():
        return str(local)
    raise RuntimeError("commande pcwatch introuvable (lance ./install.sh)")


def ssh_aliases() -> list[str]:
    """Alias de ~/.ssh/config, hors motifs et adresses link-local."""
    path = Path.home() / ".ssh" / "config"
    if not path.is_file():
        return []
    aliases: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.lower().startswith("host "):
                continue
            for alias in stripped.split()[1:]:
                if any(ch in alias for ch in "*?") or alias.startswith("169.254."):
                    continue
                if alias not in aliases:
                    aliases.append(alias)
    except OSError:
        return []
    return aliases


def sanitize_window(name: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-") or "host"
    base = base[:24]
    candidate = base
    index = 2
    while candidate in used:
        suffix = f"-{index}"
        candidate = base[: 24 - len(suffix)] + suffix
        index += 1
    used.add(candidate)
    return candidate


def resolve_hosts(
    config: Config,
    positional: list[str],
    option_hosts: str | None,
    all_ssh: bool,
) -> list[str]:
    explicit: list[str] = []
    explicit.extend(positional)
    if option_hosts:
        explicit.extend(
            part for part in re.split(r"[\s,]+", option_hosts) if part
        )
    if explicit:
        hosts = explicit
    elif config.monitor.get("hosts"):
        hosts = list(config.monitor["hosts"])
    else:
        hosts = list(config.host_names())
    if all_ssh:
        hosts.extend(ssh_aliases())
    unique: list[str] = []
    for host in hosts:
        host = host.strip()
        if host and host not in unique:
            unique.append(host)
    if not unique:
        unique = ["local"]
    return unique


def build_command(
    pcwatch: str,
    config: Config,
    host: str,
    interval: int | None,
    verbosity: str | None,
    simplicity: str | None,
) -> list[str]:
    cmd = [pcwatch]
    if host in config.hosts:
        cmd += ["--host", host]
    else:
        cmd += ["--ssh", host]
    if interval:
        cmd += ["--interval", str(interval)]
    if verbosity:
        cmd += ["--verbosity", verbosity]
    if simplicity:
        cmd += ["--simplicity", simplicity]
    return cmd


def tmux_run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(message or f"échec: {' '.join(args)}")
    return proc


def has_session(session: str) -> bool:
    return (
        subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def kill_session(session: str) -> None:
    subprocess.run(
        ["tmux", "kill-session", "-t", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_session(session: str, windows: list[tuple[str, list[str]]]) -> None:
    first_name, first_cmd = windows[0]
    tmux_run(
        [
            "tmux", "new-session", "-d", "-s", session,
            "-n", first_name,
            shlex.join(first_cmd),
        ]
    )
    for window_name, command in windows[1:]:
        tmux_run(
            [
                "tmux", "new-window", "-d",
                "-t", f"{session}:",
                "-n", window_name,
                shlex.join(command),
            ]
        )
    tmux_run(["tmux", "select-window", "-t", f"{session}:{first_name}"])


def attach_session(session: str, no_attach: bool) -> int:
    if no_attach or not sys.stdout.isatty():
        print(f"tmux attach -t {session}")
        return 0
    if os.environ.get("TMUX"):
        proc = subprocess.run(["tmux", "switch-client", "-t", session])
    else:
        proc = subprocess.run(["tmux", "attach", "-t", session])
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcwatch-lan",
        description="Une fenêtre tmux par machine, chacune avec pcwatch en TUI.",
    )
    parser.add_argument("hosts", nargs="*", help="hôtes : noms de [hosts.*] ou alias SSH")
    parser.add_argument("--hosts", dest="hosts_opt", help="liste séparée par des virgules")
    parser.add_argument("--all-ssh", action="store_true", help="ajouter les alias de ~/.ssh/config")
    parser.add_argument("--session", default=None, help="nom de session tmux (défaut: pcwatch)")
    parser.add_argument("--interval", type=int, default=None, help="intervalle pcwatch en secondes")
    parser.add_argument("--verbosity", choices=VERBOSITIES, help="verbosité pcwatch")
    parser.add_argument("--simplicity", choices=SIMPLICITIES, help="simplicité pcwatch")
    parser.add_argument("--config", help="fichier de configuration TOML")
    parser.add_argument("--list", "--dry-run", dest="list_only", action="store_true", help="afficher les commandes sans créer la session")
    parser.add_argument("--no-attach", action="store_true", help="créer la session sans s'y attacher")
    parser.add_argument("--kill", action="store_true", help="arrêter la session")
    parser.add_argument("--restart", action="store_true", help="recréer la session")
    parser.add_argument("--version", action="version", version="pcwatch-lan 0.1.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except RuntimeError as exc:
        print(f"pcwatch-lan: {exc}", file=sys.stderr)
        return 2

    session = args.session or str(config.monitor.get("session") or DEFAULT_SESSION)
    interval = args.interval
    if interval is None:
        configured = int(config.monitor.get("interval", 0) or 0)
        interval = configured if configured > 0 else None

    hosts = resolve_hosts(config, args.hosts, args.hosts_opt, args.all_ssh)
    try:
        pcwatch = pcwatch_executable()
    except RuntimeError as exc:
        print(f"pcwatch-lan: {exc}", file=sys.stderr)
        return 2

    windows: list[tuple[str, list[str]]] = []
    used_names: set[str] = set()
    for host in hosts:
        window = sanitize_window(host, used_names)
        command = build_command(pcwatch, config, host, interval, args.verbosity, args.simplicity)
        windows.append((window, command))

    if args.list_only:
        print(f"session: {session}")
        for window, command in windows:
            print(f"{window:24} {shlex.join(command)}")
        return 0

    if shutil.which("tmux") is None:
        print("pcwatch-lan: tmux est requis", file=sys.stderr)
        return 2

    if args.kill:
        kill_session(session)
        print(f"✓ session {session} arrêtée")
        return 0

    if args.restart:
        kill_session(session)

    if has_session(session):
        print(f"• session {session} déjà active")
        return attach_session(session, args.no_attach)

    try:
        create_session(session, windows)
    except RuntimeError as exc:
        print(f"pcwatch-lan: {exc}", file=sys.stderr)
        return 1

    print(f"✓ session {session} créée avec {len(windows)} fenêtre(s)")
    return attach_session(session, args.no_attach)


if __name__ == "__main__":
    raise SystemExit(main())
