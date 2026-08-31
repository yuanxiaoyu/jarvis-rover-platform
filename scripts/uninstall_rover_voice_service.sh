#!/usr/bin/env bash
set -euo pipefail
unit=/etc/systemd/system/jarvis-rover-voice.service
[[ -e "$unit" ]] || exit 0
grep -q 'Managed-By: jarvis-rover-voice-installer' "$unit" || { echo "refusing to remove unmanaged unit" >&2; exit 1; }
systemctl disable --now jarvis-rover-voice.service || true
rm -f "$unit"; systemctl daemon-reload
