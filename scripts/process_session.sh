#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if (($# < 1 || $# > 2)); then
  echo "Usage: process_session.sh SESSION_DIR [--overwrite]" >&2
  exit 2
fi
SESSION_DIR="$1"
OVERWRITE="${2:-}"
if [[ -n "${OVERWRITE}" && "${OVERWRITE}" != "--overwrite" ]]; then
  echo "Unknown option: ${OVERWRITE}" >&2
  exit 2
fi

if [[ ! -f /opt/ros/humble/setup.bash ]]; then
  echo "ROS 2 Humble was not found; extraction must run inside unitree-dev" >&2
  exit 1
fi
set +u
source /opt/ros/humble/setup.bash
set -u

extract_args=(extract --session "${SESSION_DIR}")
if [[ "${OVERWRITE}" == "--overwrite" ]]; then
  extract_args+=(--overwrite)
fi

"${SCRIPT_DIR}/duck_dataset" "${extract_args[@]}"
"${SCRIPT_DIR}/duck_dataset" validate --session "${SESSION_DIR}"
"${SCRIPT_DIR}/duck_dataset" visualize --session "${SESSION_DIR}"

echo "Session processing complete:"
echo "  ${SESSION_DIR}/artifacts/report.html"
echo "  ${SESSION_DIR}/artifacts/contact_sheet.jpg"
echo "  ${SESSION_DIR}/artifacts/preview.mp4"

