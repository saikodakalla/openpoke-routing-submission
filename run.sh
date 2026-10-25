#!/usr/bin/env bash
# The submission and host are separate folders; upstream is a local runtime dependency.
set -euo pipefail
cd "$(dirname "$0")"
submission_dir="$PWD"
host_dir="${1:?Usage: bash run.sh /path/to/openpoke [--offline|--live]}"
shift
host_dir="$(cd "$host_dir" && pwd)"
mode=offline
if [[ "${1:-}" == --live ]]; then mode=live; elif [[ "${1:---offline}" != --offline ]]; then exit 2; fi
python="$submission_dir/.venv/bin/python"
[[ -x "$python" ]] || { echo 'Run bash setup.sh first.' >&2; exit 1; }
export PYTHONPATH="$submission_dir:$host_dir"
export OPENPOKE_ENV_FILE="${OPENPOKE_ENV_FILE:-$submission_dir/.env}"
export OPENPOKE_MODE="$mode" OPENPOKE_ALLOW_LIVE=0
[[ "$mode" == live ]] && export OPENPOKE_ALLOW_LIVE=1
export OPENPOKE_EXECUTION_URL=http://127.0.0.1:8004
export OPENPOKE_DATA_DIR="${OPENPOKE_DATA_DIR:-$submission_dir/data/$mode}"
export OPENPOKE_MAX_CALLS="${OPENPOKE_MAX_CALLS:-100}" OPENPOKE_MAX_TOKENS="${OPENPOKE_MAX_TOKENS:-200000}" OPENPOKE_MAX_COST_USD="${OPENPOKE_MAX_COST_USD:-1.00}"
"$python" -c 'import socket; ports=[8003,8004,3001]; sockets=[]
for port in ports:
 s=socket.socket();s.bind(("127.0.0.1",port));sockets.append(s)
for s in sockets:s.close()'
bash integration/apply-runtime-patch.sh "$host_dir"
"$python" -c 'from pathlib import Path;import secrets;p=Path(".env.bridge.local");p.write_text("OPENPOKE_BRIDGE_TOKEN="+secrets.token_urlsafe(32)+"\n") if not p.exists() else None;p.chmod(0o600)'
set -a
source .env.bridge.local
set +a
"$python" -c 'from task_router.service import RoutingService;from task_router.dataset import seed_showcase;s=RoutingService();print(seed_showcase(s.store) if not s.store.rows("SELECT 1 FROM tasks LIMIT 1") else "Existing registry preserved. Indexing is deferred.")'
(cd "$host_dir" && "$python" -m integration.host_server) & host_pid=$!
"$python" -m uvicorn task_router.app:app --host 127.0.0.1 --port 8003 & router_pid=$!
cleanup() { kill "$host_pid" "$router_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
PY_SERVER_URL=http://127.0.0.1:8003 npm run start --prefix web -- --hostname 127.0.0.1 --port 3001
