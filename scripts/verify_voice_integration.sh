#!/usr/bin/env bash
set -Eeuo pipefail

# Offline/static integration verification. This script never calls GPT or changes ROS.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failures=0
require_file() {
  if [[ ! -f "$ROOT_DIR/$1" ]]; then
    printf 'MISSING: %s\n' "$1" >&2
    failures=$((failures + 1))
  fi
}
for path in \
  services/api/app/models/assistant.py \
  services/api/app/services/assistant_provider.py \
  services/api/app/services/assistant_service.py \
  services/voice/rover_voice/service.py \
  services/voice/rover_voice/state_machine.py \
  deploy/jarvis-rover-voice.service; do
  require_file "$path"
done
if grep -RInE '(^|[^A-Za-z0-9_])(/cmd_vel|cmd_vel)' "$ROOT_DIR/services/voice" >/dev/null 2>&1; then
  printf 'FAIL: host voice package references cmd_vel\n' >&2
  failures=$((failures + 1))
fi
if grep -RInE 'ROVER_AI_API_KEY|Authorization' "$ROOT_DIR/services/voice" >/dev/null 2>&1; then
  printf 'FAIL: host voice package references provider secret\n' >&2
  failures=$((failures + 1))
fi
if grep -nE 'Requires=rover-runtime|ExecStart=.*mapping_(start|resume)|docker compose down' "$ROOT_DIR/deploy/jarvis-rover-voice.service" >/dev/null 2>&1; then
  printf 'FAIL: voice unit has a runtime/mapping side effect\n' >&2
  failures=$((failures + 1))
fi
if ! grep -q 'X-Rover-Voice-Token' "$ROOT_DIR/services/voice/rover_voice/gateway_client.py"; then
  printf 'FAIL: gateway token header missing\n' >&2
  failures=$((failures + 1))
fi
if (( failures )); then
  printf 'voice integration verification failed: %d check(s)\n' "$failures" >&2
  exit 1
fi
printf 'voice integration static verification passed (no network, ROS, audio, or GPT call)\n'
