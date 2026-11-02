"""Chargement de la configuration TOML de PC Watch."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("Python >= 3.11 ou le paquet tomli est requis") from exc


PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RULES = PACKAGE_DIR / "rules.toml"
DEFAULT_CONFIG = Path.home() / ".config" / "pc_watch" / "config.toml"

VERBOSITIES = ("quiet", "normal", "verbose", "debug")
SIMPLICITIES = ("simple", "normal", "expert")

DEFAULTS: dict[str, Any] = {
    "general": {
        "refresh_seconds": 30,
        "verbosity": "normal",
        "simplicity": "normal",
        "history_lines": 200,
        "finding_ttl_seconds": 3600,
        "rules": "",
        "rules_local": "~/.config/pc_watch/rules.local.toml",
    },
    "thresholds": {
        "cpu_warn_percent": 90,
        "cpu_crit_percent": 98,
        "disk_warn_percent": 85,
        "disk_crit_percent": 95,
        "mem_warn_percent": 85,
        "mem_crit_percent": 95,
        "swap_warn_percent": 50,
        "swap_crit_percent": 80,
        "temp_warn_c": 75,
        "temp_crit_c": 90,
        "load_warn_per_cpu": 1.5,
        "load_crit_per_cpu": 3.0,
        "smart_temp_warn_c": 60,
        "smart_temp_crit_c": 75,
        "smart_wear_warn_percent": 80,
        "smart_wear_crit_percent": 95,
        "failed_units_warn": 1,
    },
    "logs": {
        "journal": True,
        "journal_priority": "warning",
        "journal_max_lines": 300,
        "files": [
            "/var/log/syslog",
            "/var/log/kern.log",
            "/var/log/auth.log",
        ],
        "dmesg": True,
        "max_lines_per_source": 200,
        "max_age_hours": 24,
    },
    "hosts": {
        "local": {
            "type": "local",
            "target": "",
            "port": 22,
            "identity": "",
            "connect_timeout": 5,
            "smart": True,
            "smart_sudo": False,
        }
    },
}


@dataclass
class HostConfig:
    name: str
    type: str = "local"
    target: str = ""
    port: int = 22
    identity: str = ""
    connect_timeout: int = 5
    smart: bool = True
    smart_sudo: bool = False
    ssh_options: list[str] = field(default_factory=list)

    @property
    def is_local(self) -> bool:
        return self.type == "local"

    @property
    def is_ssh(self) -> bool:
        return self.type == "ssh"


@dataclass
class Config:
    general: dict[str, Any]
    thresholds: dict[str, Any]
    logs: dict[str, Any]
    hosts: dict[str, HostConfig]
    path: Path
    rules_path: Path
    rules_local_path: Path
    warnings: list[str] = field(default_factory=list)

    @property
    def refresh_seconds(self) -> int:
        return int(self.general.get("refresh_seconds", 30))

    @property
    def verbosity(self) -> str:
        value = str(self.general.get("verbosity", "normal")).lower()
        return value if value in VERBOSITIES else "normal"

    @property
    def simplicity(self) -> str:
        value = str(self.general.get("simplicity", "normal")).lower()
        return value if value in SIMPLICITIES else "normal"

    @property
    def history_lines(self) -> int:
        return int(self.general.get("history_lines", 200))

    @property
    def finding_ttl_seconds(self) -> int:
        return int(self.general.get("finding_ttl_seconds", 3600))

    def host(self, name: str) -> HostConfig:
        try:
            return self.hosts[name]
        except KeyError as exc:
            available = ", ".join(self.host_names())
            raise KeyError(f"hôte inconnu: {name} (disponibles: {available})") from exc

    def host_names(self) -> list[str]:
        names = list(self.hosts)
        names.sort(key=lambda n: (n != "local", n))
        return names

    def thresholds_for(self, key: str, default: float) -> float:
        try:
            return float(self.thresholds.get(key, default))
        except (TypeError, ValueError):
            return default


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _expand(value: str) -> str:
    return os.path.expanduser(str(value)) if value else ""


def _resolve_path(value: str, base_dir: Path) -> Path:
    if not value:
        return DEFAULT_RULES
    path = Path(os.path.expanduser(str(value)))
    if not path.is_absolute():
        path = base_dir / path
    return path


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Charge le TOML utilisateur, ou les valeurs par défaut s'il n'existe pas."""

    config_path = Path(os.path.expanduser(str(path))) if path else DEFAULT_CONFIG
    raw: dict[str, Any] = {}
    warnings: list[str] = []
    if config_path.is_file():
        try:
            with config_path.open("rb") as f:
                raw = tomllib.load(f)
        except Exception as exc:  # noqa: BLE001 - l'utilisateur doit voir l'erreur
            raise RuntimeError(f"Impossible de lire {config_path}: {exc}") from exc
    elif path:
        warnings.append(f"config introuvable: {config_path} (valeurs par défaut)")

    merged = _deep_merge(DEFAULTS, raw)
    general = merged["general"]
    thresholds = merged["thresholds"]
    logs = merged["logs"]

    # Normalisation de quelques valeurs.
    try:
        general["refresh_seconds"] = max(2, int(general.get("refresh_seconds", 30)))
    except (TypeError, ValueError):
        general["refresh_seconds"] = 30
    if str(general.get("verbosity", "normal")).lower() not in VERBOSITIES:
        warnings.append(f"verbosity inconnue: {general.get('verbosity')!r}, normal utilisé")
        general["verbosity"] = "normal"
    if str(general.get("simplicity", "normal")).lower() not in SIMPLICITIES:
        warnings.append(f"simplicity inconnue: {general.get('simplicity')!r}, normal utilisé")
        general["simplicity"] = "normal"
    files = logs.get("files", [])
    if not isinstance(files, list):
        warnings.append("logs.files doit être une liste, valeur ignorée")
        files = []
    logs["files"] = [_expand(str(f)) for f in files]

    hosts: dict[str, HostConfig] = {}
    for name, spec in merged.get("hosts", {}).items():
        if not isinstance(spec, dict):
            warnings.append(f"hosts.{name} invalide, ignoré")
            continue
        htype = str(spec.get("type", "ssh" if spec.get("target") else "local")).lower()
        if htype not in ("local", "ssh"):
            warnings.append(f"hosts.{name}.type inconnu: {htype}, ignoré")
            continue
        try:
            port = int(spec.get("port", 22))
        except (TypeError, ValueError):
            port = 22
        hosts[name] = HostConfig(
            name=name,
            type=htype,
            target=str(spec.get("target", "")),
            port=port,
            identity=_expand(str(spec.get("identity", ""))),
            connect_timeout=max(1, int(spec.get("connect_timeout", 5))),
            smart=bool(spec.get("smart", True)),
            smart_sudo=bool(spec.get("smart_sudo", False)),
            ssh_options=[str(o) for o in spec.get("ssh_options", [])],
        )
    if "local" not in hosts:
        hosts["local"] = HostConfig(name="local", type="local")

    base_dir = config_path.parent if config_path.parent.is_dir() else Path.cwd()
    rules_path = _resolve_path(str(general.get("rules", "")), base_dir)
    rules_local = Path(_expand(str(general.get("rules_local", ""))))
    if not rules_local.is_absolute():
        rules_local = base_dir / rules_local

    return Config(
        general=general,
        thresholds=thresholds,
        logs=logs,
        hosts=hosts,
        path=config_path,
        rules_path=rules_path,
        rules_local_path=rules_local,
        warnings=warnings,
    )


def adhoc_ssh_host(
    target: str,
    port: int = 22,
    identity: str = "",
    connect_timeout: int = 5,
    smart: bool = True,
    smart_sudo: bool = False,
) -> HostConfig:
    return HostConfig(
        name=f"ssh:{target}",
        type="ssh",
        target=target,
        port=port,
        identity=_expand(identity),
        connect_timeout=connect_timeout,
        smart=smart,
        smart_sudo=smart_sudo,
    )
