#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIPER_RELEASE="${PIPER_RELEASE:-2023.11.14-2}"
PIPER_VOICE_VERSION="${PIPER_VOICE_VERSION:-v1.0.0}"
PIPER_VOICE_NAME="${PIPER_VOICE_NAME:-ru_RU-dmitri-medium}"
PIPER_VOICE_DIR="${PIPER_VOICE_DIR:-$ROOT_DIR/storage/assets/voices/piper}"
PIPER_DIR="$ROOT_DIR/third_party/piper"

mkdir -p "$PIPER_DIR" "$PIPER_VOICE_DIR"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -L --fail -o "$TMP_DIR/piper_linux_x86_64.tar.gz" \
  "https://github.com/rhasspy/piper/releases/download/${PIPER_RELEASE}/piper_linux_x86_64.tar.gz"
tar -xzf "$TMP_DIR/piper_linux_x86_64.tar.gz" -C "$TMP_DIR"

rm -rf "$PIPER_DIR/piper"
cp -a "$TMP_DIR/piper" "$PIPER_DIR/"
chmod +x "$PIPER_DIR/piper/piper"

curl -L --fail -o "$PIPER_VOICE_DIR/${PIPER_VOICE_NAME}.onnx" \
  "https://huggingface.co/rhasspy/piper-voices/resolve/${PIPER_VOICE_VERSION}/ru/ru_RU/dmitri/medium/${PIPER_VOICE_NAME}.onnx"
curl -L --fail -o "$PIPER_VOICE_DIR/${PIPER_VOICE_NAME}.onnx.json" \
  "https://huggingface.co/rhasspy/piper-voices/resolve/${PIPER_VOICE_VERSION}/ru/ru_RU/dmitri/medium/${PIPER_VOICE_NAME}.onnx.json"

echo "piper_bin=$PIPER_DIR/piper/piper"
echo "piper_model=$PIPER_VOICE_DIR/${PIPER_VOICE_NAME}.onnx"
