#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
voice_env_file=""
service_user="${ROVER_VOICE_SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
voice_python="${ROVER_VOICE_PYTHON:-}"

usage() {
  cat <<'USAGE'
usage: install_rover_voice_service.sh [options]

Options:
  --repo-dir DIR       repository containing services/voice (default: script repo)
  --voice-env-file FILE
                       voice-only environment source; if omitted, filter repo .env
  --service-user USER  systemd user with audio access (default: SUDO_USER/current user)
  --python FILE        Python executable (default: DIR/services/voice/.venv/bin/python)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-dir) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; repo_dir="$2"; shift 2 ;;
    --voice-env-file|--env-file) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; voice_env_file="$2"; shift 2 ;;
    --service-user) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; service_user="$2"; shift 2 ;;
    --python) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; voice_python="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  printf '%s\n' 'run as root to install the systemd service' >&2
  exit 2
fi

repo_dir="$(cd "$repo_dir" 2>/dev/null && pwd)" || {
  printf '%s\n' 'voice unavailable: repository directory does not exist' >&2
  exit 2
}
[[ -f "$repo_dir/deploy/jarvis-rover-voice.service" ]] || {
  printf '%s\n' 'voice unavailable: deployment unit is missing' >&2
  exit 2
}
[[ -d "$repo_dir/services/voice" ]] || {
  printf '%s\n' 'voice unavailable: services/voice is missing' >&2
  exit 2
}
id "$service_user" >/dev/null 2>&1 || {
  printf 'voice unavailable: service user does not exist: %s\n' "$service_user" >&2
  exit 2
}
service_group="$(id -gn "$service_user")"
if ! id -nG "$service_user" | tr ' ' '\n' | grep -qx audio; then
  printf 'voice unavailable: service user %s is not in the audio group\n' "$service_user" >&2
  exit 2
fi

if [[ -z "$voice_python" ]]; then
  voice_python="$repo_dir/services/voice/.venv/bin/python"
fi
[[ -x "$voice_python" ]] || {
  printf 'voice unavailable: Python executable is not available: %s\n' "$voice_python" >&2
  exit 2
}

unit_path=/etc/systemd/system/jarvis-rover-voice.service
if [[ -e "$unit_path" ]] && ! grep -q 'Managed-By: jarvis-rover-voice-installer' "$unit_path"; then
  printf '%s\n' 'refusing to overwrite unmanaged jarvis-rover-voice.service' >&2
  exit 1
fi

install -d -o root -g root -m 0755 /etc/jarvis-rover /var/lib/jarvis-rover/voice

python3 - "$repo_dir/deploy/jarvis-rover-voice.service" "$unit_path" "$repo_dir" "$service_user" "$service_group" "$voice_python" <<'PY'
from pathlib import Path
import sys

template, destination, repo_dir, service_user, service_group, voice_python = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
for marker, value in {
    "@REPO_DIR@": repo_dir,
    "@SERVICE_USER@": service_user,
    "@SERVICE_GROUP@": service_group,
    "@VOICE_PYTHON@": voice_python,
}.items():
    text = text.replace(marker, value)
if "@" in text:
    raise SystemExit("unresolved deployment placeholder")
Path(destination).write_text(text + "\n# Managed-By: jarvis-rover-voice-installer\n", encoding="utf-8")
PY
chown root:root "$unit_path"
chmod 0644 "$unit_path"

source_env="$voice_env_file"
if [[ -z "$source_env" && -f "$repo_dir/.env" ]]; then
  source_env="$repo_dir/.env"
fi
if [[ -n "$source_env" ]]; then
  [[ -r "$source_env" ]] || { printf 'voice unavailable: env file is not readable: %s\n' "$source_env" >&2; exit 2; }
  filtered_env="$(mktemp)"
  trap 'rm -f "$filtered_env"' EXIT
  # Only copy host voice settings. This deliberately excludes ROVER_AI_API_KEY
  # and all other provider configuration from the voice service.
  awk '/^(ROVER_VOICE_|ROVER_WAKEWORD_|ROVER_ASR_|ROVER_TTS_)/' "$source_env" > "$filtered_env"
  install -o root -g "$service_group" -m 0640 "$filtered_env" /etc/jarvis-rover/voice.env
  printf '%s\n' 'installed voice-only environment (provider key excluded)'
elif [[ ! -f /etc/jarvis-rover/voice.env ]]; then
  install -o root -g "$service_group" -m 0640 /dev/null /etc/jarvis-rover/voice.env
  printf '%s\n' 'created empty /etc/jarvis-rover/voice.env'
fi

systemd-analyze verify "$unit_path"
systemctl daemon-reload
systemctl enable --now jarvis-rover-voice.service
systemctl --no-pager --full status jarvis-rover-voice.service || true
