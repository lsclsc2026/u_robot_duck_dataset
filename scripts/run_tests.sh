#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ -f /opt/ros/humble/setup.bash ]]; then
  set +u
  source /opt/ros/humble/setup.bash
  set -u
fi
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

python3 -m unittest discover -s "${PROJECT_ROOT}/tests" -v

