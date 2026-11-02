"""Interface en ligne de commande de PC Watch."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .analyzer import collect_and_analyze
from .config import (
    SIMPLICITIES,
    VERBOSITIES,
    Config,
    HostConfig,
    adhoc_ssh_host,
    load_config,
)
from .report import render_report, report_json
from .rules import load_rules

VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcwatch",
        description="Surveillance de santé du PC : journaux, SMART, capteurs, TUI « Dr. PC ».",
    )
    parser.add_argument("--host", help="hôte configuré à analyser (local, raspberrypi, ...)")
    parser.add_argument("--ssh", metavar="USER@HOST", help="hôte SSH ad hoc (ex: pi@raspberrypi.local)")
    parser.add_argument("--ssh-port", type=int, default=22, help="port SSH pour --ssh (défaut: 22)")
    parser.add_argument("--ssh-identity", default="", help="clé SSH privée pour --ssh")
    parser.add_argument("--config", help="fichier de configuration TOML")
    parser.add_argument("--rules", help="fichier de règles TOML (remplace le fichier intégré)")
    parser.add_argument("--interval", type=int, help="intervalle de rafraîchissement en secondes")
    parser.add_argument("--once", action="store_true", help="rapport unique, sans TUI")
    parser.add_argument("--no-tui", action="store_true", help="alias de --once")
    parser.add_argument("--json", action="store_true", help="sortie JSON (implique --once)")
    parser.add_argument("--demo", action="store_true", help="données de démonstration")
    parser.add_argument("--verbosity", choices=VERBOSITIES, help="niveau de verbosité")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="verbeux (répétable)")
    parser.add_argument("-q", "--quiet", action="store_true", help="mode silencieux / résumé")
    parser.add_argument("--simplicity", choices=SIMPLICITIES, help="niveau de simplicité du docteur")
    parser.add_argument("--simple", dest="simplicity", action="store_const", const="simple", help="raccourci pour --simplicity simple")
    parser.add_argument("--expert", dest="simplicity", action="store_const", const="expert", help="raccourci pour --simplicity expert")
    parser.add_argument("--no-color", action="store_true", help="désactiver les couleurs Rich")
    parser.add_argument("--list-hosts", action="store_true", help="lister les hôtes configurés")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def _choose_verbosity(args: argparse.Namespace, config: Config) -> str:
    if args.verbosity:
        return args.verbosity
    if args.quiet:
        return "quiet"
    if args.verbose >= 2:
        return "debug"
    if args.verbose == 1:
        return "verbose"
    return config.verbosity


def _choose_simplicity(args: argparse.Namespace, config: Config) -> str:
    return args.simplicity or config.simplicity


def _choose_host(args: argparse.Namespace, config: Config) -> HostConfig:
    if args.ssh:
        return adhoc_ssh_host(
            target=args.ssh,
            port=args.ssh_port,
            identity=args.ssh_identity,
            smart=True,
            smart_sudo=False,
        )
    if args.host:
        try:
            return config.host(args.host)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc
    if "local" in config.hosts:
        return config.hosts["local"]
    return config.hosts[config.host_names()[0]]


def _ssh_config_aliases() -> list[str]:
    """Alias de ~/.ssh/config utilisables directement avec --ssh."""
    path = Path.home() / ".ssh" / "config"
    if not path.is_file():
        return []
    aliases: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("host "):
                for alias in stripped.split()[1:]:
                    if any(ch in alias for ch in "*?") or alias in aliases:
                        continue
                    aliases.append(alias)
    except OSError:
        return []
    return aliases


def _print_hosts(config: Config) -> None:
    for name in config.host_names():
        host = config.hosts[name]
        if host.is_ssh:
            print(f"{name:16} ssh  {host.target}  port={host.port}")
        else:
            print(f"{name:16} local")
    aliases = _ssh_config_aliases()
    if aliases:
        print("\nAlias ~/.ssh/config utilisables via --ssh :")
        print("  " + " ".join(aliases))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except RuntimeError as exc:
        print(f"pcwatch: {exc}", file=sys.stderr)
        return 2

    if args.list_hosts:
        _print_hosts(config)
        return 0

    if args.interval:
        config.general["refresh_seconds"] = max(2, int(args.interval))

    verbosity = _choose_verbosity(args, config)
    simplicity = _choose_simplicity(args, config)
    host = _choose_host(args, config)

    if args.demo:
        host = HostConfig(name="demo-pc", type="demo")

    rules_path = Path(os.path.expanduser(args.rules)) if args.rules else config.rules_path
    local_rules = None if args.rules else config.rules_local_path
    rules, rule_errors = load_rules(rules_path, local_rules)
    if not rules:
        print(
            "pcwatch: aucune règle chargée "
            f"({rules_path}); vérifiez rules.toml",
            file=sys.stderr,
        )
        for error in rule_errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    once = args.once or args.no_tui or args.json
    if once:
        report = collect_and_analyze(
            config,
            rules,
            host,
            rule_errors,
            demo=args.demo,
        )
        if args.json:
            try:
                print(report_json(report))
            except BrokenPipeError:
                return 0
        else:
            render_report(
                report,
                verbosity=verbosity,
                simplicity=simplicity,
                no_color=args.no_color,
            )
        return report.exit_code()

    try:
        from .tui import PCWatchApp
    except ImportError as exc:
        print(
            f"pcwatch: TUI indisponible ({exc}). "
            "Utilisez --once ou installez textual.",
            file=sys.stderr,
        )
        return 2

    app = PCWatchApp(
        config=config,
        rules=rules,
        host=host,
        verbosity=verbosity,
        simplicity=simplicity,
        demo=args.demo,
        rule_errors=rule_errors,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
