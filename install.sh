#!/bin/sh
# Installe la commande pcwatch dans ~/.local/bin (sans sudo).
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="${HOME}/.local/bin"

if ! command -v uv >/dev/null 2>&1; then
	echo "uv est requis : https://docs.astral.sh/uv/" >&2
	exit 1
fi

mkdir -p "$BIN"
chmod +x "$DIR/pcwatch.py"
ln -sf "$DIR/pcwatch.py" "$BIN/pcwatch"

echo "✓ ${BIN}/pcwatch -> ${DIR}/pcwatch.py"
case ":${PATH}:" in
	*":${BIN}:"*) ;;
	*) echo "⚠ ajoute ${BIN} à ton PATH" >&2 ;;
esac

echo "Test : pcwatch --version"
