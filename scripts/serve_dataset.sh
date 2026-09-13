#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="${U_ROBOT_DUCK_DATA_ROOT:-${HOME}/data/duck_dataset}"
BIND_ADDRESS="127.0.0.1"
PORT="8090"

usage() {
  cat <<'EOF'
Usage: serve_dataset.sh [--root PATH] [--bind ADDRESS] [--port PORT]

Defaults to 127.0.0.1:8090. When connected remotely, forward it to any free
local port, for example:
  ssh -N -L 18090:127.0.0.1:8090 USER@ROBOT_HOST
Then open http://127.0.0.1:18090/live in the local browser.

Use --bind 0.0.0.0 only when direct LAN access is intentionally required.
EOF
}

while (($#)); do
  case "$1" in
    --root) DATA_ROOT="${2:?missing value for --root}"; shift 2 ;;
    --bind) BIND_ADDRESS="${2:?missing value for --bind}"; shift 2 ;;
    --port) PORT="${2:?missing value for --port}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "${PORT}" =~ ^[0-9]+$ ]] || ((PORT < 1 || PORT > 65535)); then
  echo "--port must be an integer in [1, 65535]" >&2
  exit 2
fi

if [[ -f /opt/ros/humble/setup.bash ]]; then
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  unset CYCLONEDDS_URI
fi

exec "${SCRIPT_DIR}/duck_dataset" serve \
  --root "${DATA_ROOT}" --bind "${BIND_ADDRESS}" --port "${PORT}"
