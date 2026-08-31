#!/usr/bin/env bash
set -u
fail=0
for cmd in python3 arecord aplay; do command -v "$cmd" >/dev/null 2>&1 || { echo "missing prerequisite: $cmd"; fail=1; }; done
if [[ -z "${ROVER_VOICE_CAPTURE_DEVICE:-}" ]]; then echo "AUDIO_UNAVAILABLE: ROVER_VOICE_CAPTURE_DEVICE is unset"; fail=1; fi
if [[ -z "${ROVER_VOICE_PLAYBACK_DEVICE:-}" ]]; then echo "AUDIO_UNAVAILABLE: ROVER_VOICE_PLAYBACK_DEVICE is unset"; fail=1; fi
for path in "${ROVER_WAKEWORD_MODEL:-}" "${ROVER_ASR_MODEL_DIR:-}" "${ROVER_TTS_MODEL:-}" "${ROVER_TTS_CONFIG:-}"; do [[ -n "$path" && -e "$path" ]] || { echo "missing model path: ${path:-unset}"; fail=1; }; done
[[ -n "${ROVER_VOICE_GATEWAY_TOKEN:-}" ]] || { echo "missing ROVER_VOICE_GATEWAY_TOKEN"; fail=1; }
exit "$fail"
