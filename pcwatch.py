#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=0.80", "rich>=13", "psutil>=5.9"]
# ///
"""Point d'entrée de PC Watch. Voir README.md."""

import os
import sys

# Fonctionne aussi quand pcwatch.py est appelé via le symlink
# ~/.local/bin/pcwatch (le dossier réel du paquet doit être importable).
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from pcwatch_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
