#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv sync --frozen --python "$(command -v python3.12)"
npm ci --prefix web
npm run build --prefix web
printf '%s\n' 'Ready. Copy .env.example to .env and run: bash run.sh /path/to/openpoke --offline'
