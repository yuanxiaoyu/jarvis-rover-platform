#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(pwd)"; env_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-dir) repo_dir="$2"; shift 2;;
    --env-file|--voice-env-file) env_file="$2"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
unit=/etc/systemd/system/jarvis-rover-voice.service
if [[ -e "$unit" ]] && ! grep -q 'Managed-By: jarvis-rover-voice-installer' "$unit"; then echo "refusing to overwrite unmanaged unit" >&2; exit 1; fi
install -d /var/lib/jarvis-rover/voice /etc/jarvis-rover
sed "s#@REPO_DIR@#$repo_dir#g" "$repo_dir/deploy/jarvis-rover-voice.service" > "$unit"
printf '\n# Managed-By: jarvis-rover-voice-installer\n' >> "$unit"
if [[ -n "$env_file" ]]; then install -m 0600 "$env_file" /etc/jarvis-rover/voice.env; fi
systemctl daemon-reload; systemctl enable --now jarvis-rover-voice.service
