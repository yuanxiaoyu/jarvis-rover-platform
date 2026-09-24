#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  printf '%s\n' 'run as root to uninstall the systemd service' >&2
  exit 2
fi
unit_path=/etc/systemd/system/jarvis-rover-voice.service
if [[ -e "$unit_path" ]] && ! grep -q 'Managed-By: jarvis-rover-voice-installer' "$unit_path"; then
  printf '%s\n' 'refusing to remove unmanaged jarvis-rover-voice.service' >&2
  exit 1
fi
systemctl disable --now jarvis-rover-voice.service 2>/dev/null || true
rm -f "$unit_path"
systemctl daemon-reload
printf '%s\n' 'removed jarvis-rover-voice.service (voice.env was preserved)'
