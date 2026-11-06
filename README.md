# PC Watch — surveillance de santé du PC (TUI « Dr. PC »)

`PC_watch` lit les journaux importants, les métriques système, SMART et les
capteurs, puis affiche un diagnostic en langage clair dans une TUI, ou un
rapport unique en CLI. Il peut aussi analyser une autre machine par SSH
(Raspberry Pi, NAS, etc.) sans rien installer dessus.

## Installation

```sh
cd /home/laurent/scripts/Utilitaires_uv/PC_watch

# test sans installation
./pcwatch.py --help
./pcwatch.py --once --demo

# commande pcwatch dans ~/.local/bin (déjà dans le PATH)
./install.sh
pcwatch --version
pcwatch-lan --version
```

Le shebang `#!/usr/bin/env -S uv run --script` fait installer automatiquement
`textual`, `rich` et `psutil` par `uv` au premier lancement.

### Alias

```sh
alias pcwatch='uv run --script /home/laurent/scripts/Utilitaires_uv/PC_watch/pcwatch.py'
```

### Pour tous les utilisateurs

```sh
sudo ln -sf /home/laurent/scripts/Utilitaires_uv/PC_watch/pcwatch.py /usr/local/bin/pcwatch
sudo ln -sf /home/laurent/scripts/Utilitaires_uv/PC_watch/pcwatch_lan.py /usr/local/bin/pcwatch-lan
```

Moins recommandé : `uv`, le cache et la configuration sont par utilisateur.

## Utilisation

```sh
pcwatch                         # TUI
pcwatch --once                  # rapport unique
pcwatch --once --json           # JSON (cron/monitoring)
pcwatch --demo                  # données factices (TUI)
pcwatch --host raspberrypi      # hôte défini dans la config
pcwatch --ssh pi@rpi.local      # hôte SSH ad hoc
pcwatch --ssh pi@rpi --ssh-port 2222 --ssh-identity ~/.ssh/id_ed25519
pcwatch --interval 60           # rafraîchissement toutes les 60 s
pcwatch --verbosity debug       # quiet | normal | verbose | debug
pcwatch --simplicity simple     # simple | normal | expert
pcwatch --simple
pcwatch --expert
pcwatch --list-hosts
```

Codes de sortie de `--once` : `0` OK, `1` avertissement, `2` critique.

### TUI

```text
r   rafraîchir          a   analyser maintenant
v   verbosité           s   simplicité
p   pause/reprise       m   changer d'hôte
h   aide                q   quitter
```

Onglets : **Diagnostic**, **Capteurs**, **Journaux**, **Hôte / Aide**.

Les constats sont conservés dans la session pendant `finding_ttl_seconds`
(1 h par défaut), même si le journal ne les répète plus à chaque cycle.

## Configuration

```sh
mkdir -p ~/.config/pc_watch
cp config.example.toml ~/.config/pc_watch/config.toml
$EDITOR ~/.config/pc_watch/config.toml
```

Tout est en TOML. Les clés principales :

- `[general]` : `refresh_seconds`, `verbosity`, `simplicity`,
  `finding_ttl_seconds`.
- `[thresholds]` : seuils CPU/RAM/swap/disque/température/charge/SMART.
- `[logs]` : journal systemd, fichiers, `dmesg`, `max_age_hours`
  (24 h par défaut), nombre de lignes.
- `[hosts.local]` et `[hosts.<nom>]` : hôtes locaux ou SSH.

### Hôte SSH

```toml
[hosts.raspberrypi]
type = "ssh"
target = "pi@raspberrypi.local"   # ou un alias de ~/.ssh/config
port = 22
identity = "~/.ssh/id_ed25519"
connect_timeout = 5
smart = true
smart_sudo = false
```

Le tool envoie un **script shell en lecture seule** via `ssh hôte sh -s`.
Aucune installation n'est nécessaire sur la machine distante ; les commandes
absentes (`journalctl`, `sensors`, `smartctl`) sont ignorées. L'authentification
doit être par clé (ou `ssh-agent`) : `BatchMode=yes`, pas de mot de passe
interactif.

Exemples avec les alias déjà présents dans `~/.ssh/config` (visibles via
`pcwatch --list-hosts`) :

```sh
pcwatch --ssh pi1_emule_300GB_HD
pcwatch --ssh DietPiHole
pcwatch --ssh piscreen
```

## Niveaux de simplicité / verbosité

**Simplicité** (le ton du docteur) :

- `simple` : une phrase par symptôme, sans jargon.
- `normal` : symptôme + explication + conseil.
- `expert` : détail technique, preuves, commandes.

**Verbosité** (la quantité) :

- `quiet` : score + verdict + 1 constat.
- `normal` : avertissements/critiques + constantes clés.
- `verbose` : tous les constats + extraits de journaux.
- `debug` : commandes, erreurs de collecte, statistiques.

## Règles

Les règles de diagnostic sont dans `rules.toml`. Exemple :

```toml
[[rules]]
id = "kernel_io_error"
area = "disk"
severity = "critical"
pattern = '(?i)(I/O error|Buffer I/O error|critical medium error)'
title = "Erreurs d'entrée/sortie disque"
simple = "Le disque a du mal à lire ou à écrire."
normal = "Le noyau signale des erreurs d'E/S..."
expert = "Motif kernel_io_error..."
advice = "Sauvegardez..."
commands = ["sudo smartctl -a /dev/nvme0n1", "journalctl -k -p warning -b"]
```

Pour ajouter des règles sans modifier le fichier intégré :

```sh
$EDITOR ~/.config/pc_watch/rules.local.toml
```

Le fichier local surcharge les règles de même `id` et ajoute les nouvelles.
Les seuils métriques sont dans `config.toml`.

## Permissions

- Journaux systemd : être dans `systemd-journal` (c'est le cas ici).
- `/var/log/syslog`, `kern.log`, `auth.log` : groupe `adm` (c'est le cas ici).
- `dmesg` : peut être restreint (`kernel.dmesg_restrict=1`) ; le tool le signale
  et utilise aussi `journalctl`.
- SMART : `smartctl` nécessite souvent root. Deux options :
  - lancer `pcwatch` avec `sudo` (déconseillé pour la TUI) ;
  - configurer `smart_sudo = true` et une règle sudoers NOPASSWD pour
    `/usr/sbin/smartctl`, ou accepter « SMART indisponible ».
- `sensors` : paquet `lm-sensors` ; fallback `psutil`.

Le tool ne modifie rien : lectures, `journalctl`, `df`, `free`, `sensors`,
`smartctl`, `systemctl --failed`, et SSH en lecture seule.

## Surveillance périodique

- La TUI rafraîchit toutes les `refresh_seconds` et permet `r`/`a`.
- `--once` permet un timer systemd utilisateur :

```ini
# ~/.config/systemd/user/pcwatch.service
[Unit]
Description=PC Watch one-shot

[Service]
Type=oneshot
ExecStart=%h/.local/bin/pcwatch --once --json
```

```ini
# ~/.config/systemd/user/pcwatch.timer
[Unit]
Description=PC Watch toutes les 5 minutes

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

```sh
systemctl --user daemon-reload
systemctl --user enable --now pcwatch.timer
journalctl --user -u pcwatch.service -f
```

## Plusieurs machines dans tmux

`install.sh` installe aussi `pcwatch-lan`, qui crée une session tmux avec
**une fenêtre par machine** :

```sh
pcwatch-lan --list                  # dry-run : commandes prévues
pcwatch-lan                         # hôtes de [monitor].hosts
pcwatch-lan local pi1_emule_300GB_HD DietPiHole piscreen
pcwatch-lan --all-ssh               # ajoute les alias de ~/.ssh/config
```

Configuration :

```toml
[monitor]
session = "pcwatch"
interval = 60
hosts = ["local", "raspberrypi"]
```

- un nom présent dans `[hosts.*]` est lancé avec `pcwatch --host <nom>` ;
- un nom absent est traité comme un alias SSH et lancé avec
  `pcwatch --ssh <alias>` ;
- `--all-ssh` ajoute les alias de `~/.ssh/config` (hors motifs et
  `169.254.*`) ;
- `--interval`, `--verbosity` et `--simplicity` sont transmis à chaque
  `pcwatch` ;
- `--restart` recrée la session, `--kill` l’arrête, `--no-attach` la crée
  sans s’y attacher ;
- si la session existe déjà, `pcwatch-lan` s’y attache (ou fait
  `switch-client` si tu es déjà dans tmux).

Navigation dans tmux :

```text
Ctrl-b w      liste des fenêtres
Ctrl-b n/p    fenêtre suivante/précédente
Ctrl-b 1/2…   accès direct
q             quitte le pcwatch de la fenêtre
tmux kill-session -t pcwatch
```

Le wrapper ne scanne pas le réseau : il faut que les machines soient
joignables en SSH par clé (ou locales). C’est volontairement explicite pour
éviter de lancer des TUI sur des adresses qui ne répondent pas.

## Architecture

```text
pcwatch.py                  shebang uv + PEP 723, point d'entrée
pcwatch_lan.py              lanceur tmux multi-machines
pcwatch_lib/
  cli.py                    argparse, --once/--json/--demo/--host/--ssh
  config.py                 TOML, defaults, hôtes, seuils
  models.py                 Finding, Metric, LogLine, HealthReport
  collectors.py             métriques, journal, fichiers, SMART, sensors
  remote.py                 script POSIX SSH + parseur
  rules.py                  rules.toml, matching, score, verdict
  analyzer.py               logs + métriques + services -> rapport
  doctor.py                 textes « Dr. PC » simple/normal/expert
  report.py                 rendu Rich / JSON
  tui.py                    application Textual
  demo.py                   données factices
rules.toml                  règles intégrées (regex + textes)
config.example.toml         modèle de configuration
install.sh                  symlink ~/.local/bin/pcwatch
tests/                      pytest des règles, config, remote, rapport
```

## Tests

```sh
cd /home/laurent/scripts/Utilitaires_uv/PC_watch
uv run --with pytest --with textual --with rich --with psutil python -m pytest -q
```

## Limites

- Le diagnostic est **déterministe et basé sur des règles**, pas un LLM.
  C'est une aide au diagnostic, pas un avis médical ni une garantie.
- Chaque cycle relit les N dernières lignes ; la TUI conserve les constats
  récents pendant `finding_ttl_seconds`.
- Les journaux très volumineux ou les formats non standard peuvent nécessiter
  d'ajuster `rules.toml`.
- Le SSH distant ne fait pas de suivi d'offset persistant : il relit les
  dernières lignes à chaque cycle.
- SMART dépend des permissions et du matériel.
