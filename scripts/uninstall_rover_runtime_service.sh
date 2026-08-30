#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="jarvis-rover-runtime.service"
UNIT_PATH="/etc/systemd/system/$UNIT_NAME"
MARKER="# Managed-By: jarvis-rover-runtime-installer"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ $EUID -eq 0 ]] || fail "run as root: sudo ${0}"

if [[ -e "$UNIT_PATH" ]] && ! grep -Fqx "$MARKER" "$UNIT_PATH"; then
  fail "refusing to remove unmanaged unit: $UNIT_PATH"
fi

systemctl disable --now jarvis-rover-runtime.service || true
rm -f "$UNIT_PATH"
systemctl daemon-reload
systemctl reset-failed "$UNIT_NAME" || true
printf 'Removed %s; map data, images, volumes, and official hardware were not touched.\n' "$UNIT_NAME"
