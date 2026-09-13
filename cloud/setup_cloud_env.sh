#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  echo "Usage: setup_cloud_env.sh [WORKSPACE] (default: U_ROBOT_DUCK_CLOUD_ROOT or ~/duck_auto_label)"
  echo "Requires prepared offline assets; installs locally and runs a CUDA smoke test."
  exit 0
fi
workspace="${1:-${U_ROBOT_DUCK_CLOUD_ROOT:-${HOME}/duck_auto_label}}"
offline_dir="${workspace}/offline"
conda_dir="${workspace}/miniconda3"
venv_dir="${workspace}/.venv"
repo_dir="${workspace}/third_party/Grounded-SAM-2"
installer="${offline_dir}/Miniconda3-py310_26.7.1-1-Linux-x86_64.sh"
wheelhouse="${offline_dir}/wheelhouse"
lockfile="${offline_dir}/requirements-cu121.lock"
source_archive="${offline_dir}/Grounded-SAM-2-b7a9c29.tar.gz"

for required in "${installer}" "${lockfile}" "${source_archive}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing offline asset: ${required}" >&2
    exit 2
  fi
done

mkdir -p "${workspace}" "${workspace}/third_party" "${workspace}/results" "${workspace}/logs"

if [[ ! -x "${conda_dir}/bin/python" ]]; then
  bash "${installer}" -b -p "${conda_dir}"
fi

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  "${conda_dir}/bin/python" -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip config --site set global.index-url \
  https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null
"${venv_dir}/bin/python" -m pip config --site set global.timeout 120 >/dev/null
"${venv_dir}/bin/python" -m pip install \
  --no-index --find-links "${wheelhouse}" --only-binary=:all: \
  -r "${lockfile}"

if [[ ! -d "${repo_dir}/sam2" ]]; then
  staging="${workspace}/third_party/.grounded_sam2_extract"
  rm -rf "${staging}"
  mkdir -p "${staging}"
  tar -xzf "${source_archive}" -C "${staging}"
  mv "${staging}/Grounded-SAM-2" "${repo_dir}"
  rmdir "${staging}"
fi

SAM2_BUILD_CUDA=0 "${venv_dir}/bin/python" -m pip install \
  --no-index --no-deps --no-build-isolation -e "${repo_dir}"

"${venv_dir}/bin/python" - <<'PY'
import torch
import torchvision
import transformers
import sam2

assert torch.cuda.is_available(), "PyTorch cannot see CUDA"
x = torch.ones((256, 256), device="cuda")
y = x @ x
torch.cuda.synchronize()
print("python:      OK")
print("torch:       ", torch.__version__)
print("torchvision: ", torchvision.__version__)
print("transformers:", transformers.__version__)
print("torch CUDA:  ", torch.version.cuda)
print("GPU:         ", torch.cuda.get_device_name(0))
print("CUDA smoke:  ", float(y[0, 0]))
PY

cat <<EOF

Environment ready.
Activate with:
  source ${venv_dir}/bin/activate
EOF
