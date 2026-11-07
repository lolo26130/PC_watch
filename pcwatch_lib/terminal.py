"""Ouverture d'un terminal local ou SSH pour l'hôte analysé."""

from __future__ import annotations

import os
import shlex
import subprocess

from .config import HostConfig


class TerminalError(RuntimeError):
    """Erreur d'ouverture ou de pilotage du terminal."""


def ssh_argv(host: HostConfig) -> list[str] | None:
    """Commande interactive pour l'hôte, ou None si aucun terminal n'est possible.

    Contrairement à la collecte, aucun ``BatchMode=yes`` n'est ajouté :
    mot de passe, passphrase et 2FA restent possibles.
    """

    if host.is_ssh:
        if not host.target:
            return None
        argv = ["ssh"]
        if host.identity:
            argv += ["-i", host.identity]
        if host.port != 22:
            argv += ["-p", str(host.port)]
        argv += list(host.ssh_options)
        argv.append(host.target)
        return argv
    if host.is_local:
        return [os.environ.get("SHELL") or "/bin/sh"]
    return None


def in_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def _tmux(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(["tmux", *args], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TerminalError("tmux introuvable") from exc
    except OSError as exc:
        raise TerminalError(str(exc)) from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        raise TerminalError(message or f"échec tmux {' '.join(args)}")
    return proc


def pane_alive(pane_id: str) -> bool:
    """Vrai si l'identifiant de panneau tmux existe encore."""

    if not pane_id:
        return False
    try:
        proc = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_id}"],
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def open_pane(host: HostConfig, existing: str | None = None) -> str:
    """Ouvre (ou réutilise) un panneau tmux sous la TUI. Retourne son id."""

    argv = ssh_argv(host)
    if argv is None:
        raise TerminalError(f"aucun terminal possible pour l'hôte {host.name}")

    if existing and pane_alive(existing):
        _tmux(["select-pane", "-t", existing])
        return existing

    args = ["split-window", "-v", "-l", "45%", "-P", "-F", "#{pane_id}"]
    target = os.environ.get("TMUX_PANE", "")
    if target:
        args += ["-t", target]
    args.append(shlex.join(argv))
    output = _tmux(args).stdout.strip().splitlines()
    if not output:
        raise TerminalError("tmux n'a pas retourné d'identifiant de panneau")
    pane = output[-1].strip()

    label = f"ssh {host.target}" if host.is_ssh else "shell local"
    try:
        _tmux(["select-pane", "-t", pane, "-T", label])
    except TerminalError:
        pass  # le titre n'est pas indispensable
    return pane


def send_literal(pane_id: str, text: str) -> None:
    """Tape ``text`` dans le panneau sans appuyer sur Entrée."""

    if not pane_alive(pane_id):
        raise TerminalError("le panneau terminal n'est plus ouvert")
    _tmux(["send-keys", "-t", pane_id, "-l", "--", text])


def run_interactive(host: HostConfig) -> int:
    """Lance ssh/shell au premier plan (après suspension de la TUI)."""

    argv = ssh_argv(host)
    if argv is None:
        raise TerminalError(f"aucun terminal possible pour l'hôte {host.name}")
    try:
        return subprocess.call(argv)
    except FileNotFoundError as exc:
        raise TerminalError(f"commande introuvable : {argv[0]}") from exc
    except OSError as exc:
        raise TerminalError(str(exc)) from exc
