#!/usr/bin/env bash
set -euo pipefail

: "${ROVER_VOICE_CAPTURE_DEVICE:?ROVER_VOICE_CAPTURE_DEVICE is required}"
: "${ROVER_VOICE_PLAYBACK_DEVICE:?ROVER_VOICE_PLAYBACK_DEVICE is required}"
: "${ROVER_WAKEWORD_MODEL:?ROVER_WAKEWORD_MODEL is required}"
: "${ROVER_ASR_MODEL_DIR:?ROVER_ASR_MODEL_DIR is required}"
: "${ROVER_TTS_MODEL:?ROVER_TTS_MODEL is required}"
: "${ROVER_TTS_CONFIG:?ROVER_TTS_CONFIG is required}"
for path in "$ROVER_WAKEWORD_MODEL" "$ROVER_ASR_MODEL_DIR" "$ROVER_TTS_MODEL" "$ROVER_TTS_CONFIG"; do
  [[ -r "$path" ]] || { printf 'model unavailable: %s\n' "$path" >&2; exit 1; }
done
command -v arecord >/dev/null || { echo "arecord unavailable" >&2; exit 1; }
command -v aplay >/dev/null || { echo "aplay unavailable" >&2; exit 1; }
command -v piper >/dev/null || { echo "piper unavailable" >&2; exit 1; }

# Capture is discarded immediately; no audio file is retained.
timeout 3 arecord -q -D "$ROVER_VOICE_CAPTURE_DEVICE" -f S16_LE -r 16000 -c 1 -t raw -d 1 /dev/null
printf 'capture: 16 kHz mono PCM16 OK\n'

if [[ "${1:-}" == "--play-test-tone" ]]; then
  command -v speaker-test >/dev/null || { echo "speaker-test unavailable" >&2; exit 1; }
  speaker-test -q -D "$ROVER_VOICE_PLAYBACK_DEVICE" -t sine -f 440 -l 1 >/dev/null
  printf 'playback: explicit test tone OK\n'
else
  printf 'playback: not exercised (pass --play-test-tone only with explicit approval)\n'
fi

printf 'model files readable; Piper executable available\n'
