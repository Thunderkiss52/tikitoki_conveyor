#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$ROOT_DIR/third_party/ComfyUI}"
HF_BIN="$COMFYUI_DIR/.venv/bin/hf"

CHECKPOINT_REPO="${CHECKPOINT_REPO:-Comfy-Org/stable-diffusion-v1-5-archive}"
CHECKPOINT_FILE="${CHECKPOINT_FILE:-v1-5-pruned-emaonly-fp16.safetensors}"
MOTION_REPO="${MOTION_REPO:-conrevo/AnimateDiff-A1111}"
MOTION_FILE="${MOTION_FILE:-motion_module/mm_sd15_v2.safetensors}"

CHECKPOINT_DIR="$COMFYUI_DIR/models/checkpoints"
MOTION_DIR="$COMFYUI_DIR/models/animatediff_models"
CHECKPOINT_NAME="$(basename "$CHECKPOINT_FILE")"
MOTION_NAME="$(basename "$MOTION_FILE")"

if [ ! -x "$HF_BIN" ]; then
  echo "hf CLI not found at $HF_BIN. Run scripts/install_comfyui_stack.sh first." >&2
  exit 1
fi

mkdir -p "$CHECKPOINT_DIR" "$MOTION_DIR"

if [ ! -f "$CHECKPOINT_DIR/$CHECKPOINT_NAME" ]; then
  "$HF_BIN" download "$CHECKPOINT_REPO" "$CHECKPOINT_FILE" --local-dir "$CHECKPOINT_DIR" --max-workers 4
fi

if [ ! -f "$MOTION_DIR/$MOTION_NAME" ]; then
  "$HF_BIN" download "$MOTION_REPO" "$MOTION_FILE" --local-dir "$MOTION_DIR" --max-workers 4
fi

if [ -f "$MOTION_DIR/$MOTION_FILE" ]; then
  mv "$MOTION_DIR/$MOTION_FILE" "$MOTION_DIR/$MOTION_NAME"
  rmdir "$(dirname "$MOTION_DIR/$MOTION_FILE")" 2>/dev/null || true
fi

echo "checkpoint=$CHECKPOINT_DIR/$CHECKPOINT_NAME"
echo "motion_model=$MOTION_DIR/$MOTION_NAME"
