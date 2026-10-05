#!/bin/sh
set -eu
umask 077
mkdir -p "$PEAT_DATA_DIR" "$HOME"
exec python -m peat
