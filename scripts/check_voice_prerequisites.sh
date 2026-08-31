#!/usr/bin/env bash
set -u
fail=0
report_failure() { printf '%s\n' "$1" >&2; fail=1; }
for cmd in python3 arecord aplay curl; do command -v "$cmd" >/dev/null 2>&1 || report_failure "missing prerequisite: $cmd"; done
for variable in ROVER_VOICE_CAPTURE_DEVICE ROVER_VOICE_PLAYBACK_DEVICE ROVER_VOICE_GATEWAY_TOKEN; do
  [[ -n "${!variable:-}" ]] || report_failure "missing $variable"
done
for path in "${ROVER_WAKEWORD_MODEL:-}" "${ROVER_ASR_MODEL_DIR:-}" "${ROVER_TTS_MODEL:-}" "${ROVER_TTS_CONFIG:-}"; do
  [[ -n "$path" && -e "$path" && -r "$path" ]] || report_failure "missing or unreadable model path: ${path:-unset}"
done
if command -v arecord >/dev/null 2>&1 && [[ -n "${ROVER_VOICE_CAPTURE_DEVICE:-}" ]]; then
  arecord -q -D "$ROVER_VOICE_CAPTURE_DEVICE" --dump-hw-params -f S16_LE -r 16000 -c 1 -d 1 /dev/null >/dev/null 2>&1 || report_failure "AUDIO_UNAVAILABLE: capture device cannot open"
fi
if command -v aplay >/dev/null 2>&1 && [[ -n "${ROVER_VOICE_PLAYBACK_DEVICE:-}" ]]; then
  aplay -q -D "$ROVER_VOICE_PLAYBACK_DEVICE" --dump-hw-params -f S16_LE -r 16000 -c 1 /dev/null >/dev/null 2>&1 || report_failure "AUDIO_UNAVAILABLE: playback device cannot open"
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl is-active --quiet jarvis-rover-runtime.service || report_failure "runtime service is not active"
fi
if command -v curl >/dev/null 2>&1; then
  curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health >/dev/null || report_failure "runtime health endpoint unavailable"
fi
if (( fail )); then exit 1; fi
printf 'voice prerequisites passed (no GPT request and no mapping command)\n'
