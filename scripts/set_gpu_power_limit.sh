#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PERCENT="${1:-90}"

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "powershell.exe was not found. Run scripts/set_gpu_power_limit.ps1 from Windows PowerShell as Administrator." >&2
  exit 1
fi

SCRIPT_WIN_PATH="$(wslpath -w "$ROOT_DIR/scripts/set_gpu_power_limit.ps1")"
exec powershell.exe -ExecutionPolicy Bypass -File "$SCRIPT_WIN_PATH" -Percent "$PERCENT"
