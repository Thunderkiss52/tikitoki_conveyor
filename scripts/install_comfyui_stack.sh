#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$ROOT_DIR/third_party/ComfyUI}"
COMFYUI_REF="${COMFYUI_REF:-v0.19.3}"
INSTALL_BASE_MODELS="${INSTALL_BASE_MODELS:-1}"
COMFYUI_TORCH_FLAVOR="${COMFYUI_TORCH_FLAVOR:-auto}"
COMFYUI_TORCH_VERSION="${COMFYUI_TORCH_VERSION:-2.10.0}"
COMFYUI_TORCHVISION_VERSION="${COMFYUI_TORCHVISION_VERSION:-0.25.0}"
COMFYUI_TORCHAUDIO_VERSION="${COMFYUI_TORCHAUDIO_VERSION:-2.10.0}"

clone_if_missing() {
  local repo_url="$1"
  local dest_dir="$2"

  if [ ! -d "$dest_dir/.git" ]; then
    git clone --depth 1 "$repo_url" "$dest_dir"
  fi
}

detect_cuda_driver_version() {
  /bin/bash -lc '
    set -euo pipefail
    if [ -d /usr/lib/wsl/lib ]; then
      export PATH=/usr/lib/wsl/lib:$PATH
      export LD_LIBRARY_PATH=/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
    fi
    python3 - <<'"'"'PY'"'"'
import ctypes

lib_names = ["libcuda.so", "libcuda.so.1"]
lib = None
for name in lib_names:
    try:
        lib = ctypes.CDLL(name)
        break
    except OSError:
        pass

if lib is None:
    print(0)
    raise SystemExit

version = ctypes.c_int()
if lib.cuInit(0) != 0 or lib.cuDriverGetVersion(ctypes.byref(version)) != 0:
    print(0)
else:
    print(version.value)
PY
  '
}

select_torch_flavor() {
  local requested="$1"
  local driver_version

  if [ "$requested" != "auto" ]; then
    printf '%s\n' "$requested"
    return
  fi

  driver_version="$(detect_cuda_driver_version || true)"
  driver_version="${driver_version:-0}"

  if [ "$driver_version" -ge 13000 ]; then
    printf 'cu130\n'
  elif [ "$driver_version" -ge 12800 ]; then
    printf 'cu128\n'
  elif [ "$driver_version" -ge 12600 ]; then
    printf 'cu126\n'
  else
    printf 'cpu\n'
  fi
}

install_torch_runtime() {
  local flavor="$1"
  local index_url="https://download.pytorch.org/whl/$flavor"

  ./.venv/bin/pip install --upgrade --force-reinstall \
    "torch==$COMFYUI_TORCH_VERSION" \
    "torchvision==$COMFYUI_TORCHVISION_VERSION" \
    "torchaudio==$COMFYUI_TORCHAUDIO_VERSION" \
    --index-url "$index_url"
}

mkdir -p "$(dirname "$COMFYUI_DIR")"

if [ ! -d "$COMFYUI_DIR/.git" ]; then
  git clone --depth 1 --branch "$COMFYUI_REF" https://github.com/Comfy-Org/ComfyUI.git "$COMFYUI_DIR"
fi

cd "$COMFYUI_DIR"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -r manager_requirements.txt

TORCH_FLAVOR="$(select_torch_flavor "$COMFYUI_TORCH_FLAVOR")"
install_torch_runtime "$TORCH_FLAVOR"

mkdir -p custom_nodes

clone_if_missing https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git custom_nodes/ComfyUI-AnimateDiff-Evolved
clone_if_missing https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git custom_nodes/ComfyUI-VideoHelperSuite

if [ -f custom_nodes/ComfyUI-AnimateDiff-Evolved/requirements.txt ]; then
  ./.venv/bin/pip install -r custom_nodes/ComfyUI-AnimateDiff-Evolved/requirements.txt
fi

if [ -f custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt ]; then
  ./.venv/bin/pip install -r custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt
fi

mkdir -p models/checkpoints models/animatediff_models input output temp

if [ "$INSTALL_BASE_MODELS" = "1" ]; then
  "$ROOT_DIR/scripts/download_comfyui_basics.sh"
fi

echo "torch_flavor=$TORCH_FLAVOR"
echo "comfyui_dir=$COMFYUI_DIR"
