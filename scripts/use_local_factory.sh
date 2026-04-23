#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_BASE_URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
COMFYUI_DEVICE_MODE="${COMFYUI_DEVICE_MODE:-gpu}"
RUNTIME_DIR="$ROOT_DIR/storage/runtime"
LOG_PATH="$RUNTIME_DIR/comfyui_wrapper.log"
STARTED_BY_WRAPPER=0
STARTED_PID=""
SAFE_THERMAL_MODE="${FACTORY_SAFE_THERMAL_MODE:-0}"
GPU_POWER_LIMIT_PERCENT="${GPU_POWER_LIMIT_PERCENT:-}"
QUALITY_EXPLICIT=0
COMFYUI_ARGS_USER="${COMFYUI_ARGS:-}"
RUN_ARGS=()
VIDEO_PROVIDER="reference"

mkdir -p "$RUNTIME_DIR"

if [ -d /usr/lib/wsl/lib ]; then
  export PATH="/usr/lib/wsl/lib:$PATH"
  export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

cleanup() {
  if [ "$STARTED_BY_WRAPPER" = "1" ] && [ -n "$STARTED_PID" ] && kill -0 "$STARTED_PID" 2>/dev/null; then
    kill "$STARTED_PID" 2>/dev/null || true
    wait "$STARTED_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

print_help() {
  cat <<'EOF'
Usage:
  bash scripts/use_local_factory.sh [wrapper options] [run_local_hodor options]

Wrapper options:
  --safe-thermal              Enable lower-heat mode. Adds --lowvram, defaults quality to standard, and tries 90% GPU power cap.
  --no-safe-thermal           Disable lower-heat mode.
  --gpu-power-limit-percent N Try to set the NVIDIA power limit to N percent of default via Windows UAC before render. Use 'off' to skip.
  -h, --help                  Show this help.

Examples:
  bash scripts/use_local_factory.sh --scenario closed_door --output-prefix hodor_ready
  bash scripts/use_local_factory.sh --safe-thermal --scenario closed_door --trend-video /path/to/trend.mp4
  bash scripts/use_local_factory.sh --provider comfyui --mode image_to_video --quality standard
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      print_help
      exit 0
      ;;
    --safe-thermal)
      SAFE_THERMAL_MODE=1
      shift
      ;;
    --no-safe-thermal)
      SAFE_THERMAL_MODE=0
      shift
      ;;
    --gpu-power-limit-percent)
      if [ "$#" -lt 2 ]; then
        echo "--gpu-power-limit-percent expects a value like 90" >&2
        exit 1
      fi
      GPU_POWER_LIMIT_PERCENT="$2"
      shift 2
      ;;
    --quality)
      QUALITY_EXPLICIT=1
      RUN_ARGS+=("$1")
      if [ "$#" -lt 2 ]; then
        echo "--quality expects a value" >&2
        exit 1
      fi
      RUN_ARGS+=("$2")
      shift 2
      ;;
    --provider)
      if [ "$#" -lt 2 ]; then
        echo "--provider expects a value" >&2
        exit 1
      fi
      VIDEO_PROVIDER="$2"
      RUN_ARGS+=("$1" "$2")
      shift 2
      ;;
    *)
      RUN_ARGS+=("$1")
      shift
      ;;
  esac
done

if [ "$SAFE_THERMAL_MODE" = "1" ]; then
  if [ -z "$GPU_POWER_LIMIT_PERCENT" ]; then
    GPU_POWER_LIMIT_PERCENT=90
  fi
  if [ "$QUALITY_EXPLICIT" = "0" ]; then
    RUN_ARGS+=(--quality standard)
  fi
  if [[ " $COMFYUI_ARGS_USER " != *" --lowvram "* ]]; then
    COMFYUI_ARGS_USER="${COMFYUI_ARGS_USER:+$COMFYUI_ARGS_USER }--lowvram"
  fi
fi

case "${GPU_POWER_LIMIT_PERCENT,,}" in
  "" )
    ;;
  off|none|skip|0|false)
    GPU_POWER_LIMIT_PERCENT=""
    ;;
esac

export COMFYUI_ARGS="$COMFYUI_ARGS_USER"

if [ -n "$GPU_POWER_LIMIT_PERCENT" ]; then
  if ! bash "$ROOT_DIR/scripts/set_gpu_power_limit.sh" "$GPU_POWER_LIMIT_PERCENT"; then
    echo "Warning: failed to set GPU power limit to ${GPU_POWER_LIMIT_PERCENT}%." >&2
  fi
fi

comfyui_ready() {
  curl -fsS "$COMFYUI_BASE_URL/system_stats" >/dev/null 2>&1
}

if [ "${VIDEO_PROVIDER,,}" = "comfyui" ] && ! comfyui_ready; then
  STARTED_BY_WRAPPER=1
  (
    cd "$ROOT_DIR"
    COMFYUI_DEVICE_MODE="$COMFYUI_DEVICE_MODE" COMFYUI_ARGS="$COMFYUI_ARGS" ./scripts/start_comfyui.sh >>"$LOG_PATH" 2>&1
  ) &
  STARTED_PID="$!"

  for _ in $(seq 1 120); do
    if comfyui_ready; then
      break
    fi
    if ! kill -0 "$STARTED_PID" 2>/dev/null; then
      echo "ComfyUI failed to start. Log tail:" >&2
      tail -n 40 "$LOG_PATH" >&2 || true
      exit 1
    fi
    sleep 2
  done

  if ! comfyui_ready; then
    echo "Timed out waiting for ComfyUI at $COMFYUI_BASE_URL. Log tail:" >&2
    tail -n 40 "$LOG_PATH" >&2 || true
    exit 1
  fi
fi

cd "$ROOT_DIR"
./.venv/bin/python scripts/run_local_hodor.py --no-auto-start-comfyui "${RUN_ARGS[@]}"
