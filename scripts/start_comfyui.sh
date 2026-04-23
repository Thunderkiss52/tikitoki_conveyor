#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$ROOT_DIR/third_party/ComfyUI}"
COMFYUI_HOST="${COMFYUI_HOST:-0.0.0.0}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_ENABLE_MANAGER="${COMFYUI_ENABLE_MANAGER:-1}"
COMFYUI_DEVICE_MODE="${COMFYUI_DEVICE_MODE:-auto}"
COMFYUI_ARGS="${COMFYUI_ARGS:-}"

if [ -d /usr/lib/wsl/lib ]; then
  export PATH="/usr/lib/wsl/lib:$PATH"
  export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [ ! -d "$COMFYUI_DIR" ]; then
  echo "ComfyUI directory not found at $COMFYUI_DIR. Run scripts/install_comfyui_stack.sh first." >&2
  exit 1
fi

if [ ! -x "$COMFYUI_DIR/.venv/bin/python" ]; then
  echo "ComfyUI virtualenv is missing at $COMFYUI_DIR/.venv. Run scripts/install_comfyui_stack.sh first." >&2
  exit 1
fi

export PYTHONUNBUFFERED=1
export HF_HUB_DISABLE_TELEMETRY=1

if [ -z "${VHS_FORCE_FFMPEG_PATH:-}" ]; then
  VHS_FORCE_FFMPEG_PATH="$("$COMFYUI_DIR/.venv/bin/python" -c "from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())")"
  export VHS_FORCE_FFMPEG_PATH
fi

cd "$COMFYUI_DIR"

args=(--listen "$COMFYUI_HOST" --port "$COMFYUI_PORT" --disable-auto-launch)

if [ "$COMFYUI_ENABLE_MANAGER" = "1" ]; then
  args+=(--enable-manager)
fi

readarray -t torch_probe < <("$COMFYUI_DIR/.venv/bin/python" - <<'PY'
import ctypes
import torch

driver_version = 0
for name in ("libcuda.so", "libcuda.so.1"):
    try:
        lib = ctypes.CDLL(name)
        version = ctypes.c_int()
        if lib.cuInit(0) == 0 and lib.cuDriverGetVersion(ctypes.byref(version)) == 0:
            driver_version = version.value
        break
    except OSError:
        pass

print("gpu" if torch.cuda.is_available() else "cpu")
print(torch.version.cuda or "none")
print(driver_version)
print(torch.cuda.device_count())
PY
)

detected_device="${torch_probe[0]}"
detected_cuda_runtime="${torch_probe[1]}"
detected_driver_version="${torch_probe[2]}"
detected_device_count="${torch_probe[3]}"

case "$COMFYUI_DEVICE_MODE" in
  auto)
    if [ "$detected_device" = "cpu" ]; then
      args+=(--cpu)
    fi
    ;;
  cpu)
    args+=(--cpu)
    ;;
  gpu)
    if [ "$detected_device" != "gpu" ]; then
      echo "GPU mode requested, but torch cannot use CUDA. runtime=$detected_cuda_runtime driver=$detected_driver_version device_count=$detected_device_count" >&2
      exit 1
    fi
    ;;
  *)
    echo "Unsupported COMFYUI_DEVICE_MODE=$COMFYUI_DEVICE_MODE. Use auto, cpu, or gpu." >&2
    exit 1
    ;;
esac

if [ -n "$COMFYUI_ARGS" ]; then
  # shellcheck disable=SC2206
  extra_args=($COMFYUI_ARGS)
  args+=("${extra_args[@]}")
fi

echo "Starting ComfyUI on http://$COMFYUI_HOST:$COMFYUI_PORT (device_mode=$COMFYUI_DEVICE_MODE detected=$detected_device cuda_runtime=$detected_cuda_runtime driver=$detected_driver_version devices=$detected_device_count)"
exec "$COMFYUI_DIR/.venv/bin/python" main.py "${args[@]}"
