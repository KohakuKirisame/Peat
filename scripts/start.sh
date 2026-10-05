#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip --isolated install --require-hashes -r requirements.lock
(cd frontend && npm ci --registry=https://registry.npmjs.org --no-audit --no-fund && npm run build)
exec .venv/bin/python -m peat
