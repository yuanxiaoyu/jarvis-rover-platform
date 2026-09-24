#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

printf '%s\n' 'checking configured ALSA devices (read-only)'
command -v arecord >/dev/null || { printf '%s\n' 'unavailable: arecord' >&2; exit 2; }
command -v aplay >/dev/null || { printf '%s\n' 'unavailable: aplay' >&2; exit 2; }
[[ -n "${ROVER_VOICE_CAPTURE_DEVICE:-}" ]] || { printf '%s\n' 'unavailable: capture device is not configured' >&2; exit 2; }
[[ -n "${ROVER_VOICE_PLAYBACK_DEVICE:-}" ]] || { printf '%s\n' 'unavailable: playback device is not configured' >&2; exit 2; }

if ! timeout 3 arecord -q -D "$ROVER_VOICE_CAPTURE_DEVICE" -f S16_LE -r 16000 -c 1 -d 1 -t raw /dev/null >/dev/null 2>&1; then
  printf '%s\n' 'unavailable: capture device cannot be opened' >&2
  exit 2
fi
if ! timeout 3 aplay -q -D "$ROVER_VOICE_PLAYBACK_DEVICE" -f S16_LE -r 8000 -c 1 -d 1 -t raw /dev/zero >/dev/null 2>&1; then
  printf '%s\n' 'unavailable: playback device cannot be opened' >&2
  exit 2
fi

if [[ "${1:-}" == "--play-test-tone" ]]; then
  command -v speaker-test >/dev/null || { printf '%s\n' 'unavailable: speaker-test' >&2; exit 2; }
  printf '%s\n' 'playing one explicit test tone'
  timeout 3 speaker-test -q -D "$ROVER_VOICE_PLAYBACK_DEVICE" -t sine -f 440 -l 1 >/dev/null
else
  printf '%s\n' 'ALSA devices are available; no test tone played (use --play-test-tone to authorize playback)'
fi
