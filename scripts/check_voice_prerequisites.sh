#!/usr/bin/env bash
set -euo pipefail

# Read local deployment configuration without printing any secret values.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

if [[ "${ROVER_VOICE_ENABLED:-false}" != "true" ]]; then
  printf '%s\n' 'voice disabled (ROVER_VOICE_ENABLED is not true)'
  exit 0
fi

fail() {
  printf 'voice unavailable: %s\n' "$1" >&2
  exit 2
}

[[ -n "${ROVER_VOICE_CAPTURE_DEVICE:-}" ]] || fail 'capture device is not configured'
[[ -n "${ROVER_VOICE_PLAYBACK_DEVICE:-}" ]] || fail 'playback device is not configured'
[[ -n "${ROVER_WAKEWORD_PHRASE-贾维斯}" ]] || fail 'wakeword phrase is not configured'
[[ "${ROVER_VOICE_SAMPLE_RATE:-16000}" == "16000" ]] || fail 'capture sample rate must be 16000'
[[ "${ROVER_VOICE_CHANNELS:-1}" == "1" ]] || fail 'capture must be mono'
command -v arecord >/dev/null || fail 'arecord is unavailable'
command -v aplay >/dev/null || fail 'aplay is unavailable'

for path_var in ROVER_WAKEWORD_MODEL ROVER_ASR_MODEL_DIR ROVER_TTS_MODEL_DIR; do
  [[ -n "${!path_var:-}" ]] || fail "$path_var is not configured"
done
tts_engine="${ROVER_TTS_ENGINE:-pocket_tts}"
[[ "$tts_engine" == "pocket_tts" || "$tts_engine" == "sherpa_vits" ]] || fail 'ROVER_TTS_ENGINE must be pocket_tts or sherpa_vits'
([[ -f "$ROVER_WAKEWORD_MODEL" || -d "$ROVER_WAKEWORD_MODEL" ]] && [[ -r "$ROVER_WAKEWORD_MODEL" ]]) || fail 'wakeword model file/directory is not readable'
if [[ -d "$ROVER_WAKEWORD_MODEL" ]]; then
  [[ -f "$ROVER_WAKEWORD_MODEL/tokens.txt" ]] || fail 'KWS tokens.txt is missing'
  compgen -G "$ROVER_WAKEWORD_MODEL/*encoder*.onnx" >/dev/null || fail 'KWS encoder model is missing'
  compgen -G "$ROVER_WAKEWORD_MODEL/*decoder*.onnx" >/dev/null || fail 'KWS decoder model is missing'
  compgen -G "$ROVER_WAKEWORD_MODEL/*joiner*.onnx" >/dev/null || fail 'KWS joiner model is missing'
  [[ -f "$ROVER_WAKEWORD_MODEL/keywords.txt" || -f "$ROVER_WAKEWORD_MODEL/test_wavs/keywords.txt" ]] || fail 'KWS keywords.txt is missing'
fi
if [[ -n "${ROVER_WAKEWORD_KEYWORDS_FILE:-}" ]]; then
  [[ -f "$ROVER_WAKEWORD_KEYWORDS_FILE" && -r "$ROVER_WAKEWORD_KEYWORDS_FILE" ]] || fail 'configured wakeword keywords file is not readable'
  grep -Fq "@${ROVER_WAKEWORD_PHRASE:-贾维斯}" "$ROVER_WAKEWORD_KEYWORDS_FILE" || fail 'configured wakeword keywords file does not contain the wakeword phrase'
fi
[[ -d "$ROVER_ASR_MODEL_DIR" && -r "$ROVER_ASR_MODEL_DIR" ]] || fail 'ASR model directory is not readable'
[[ -f "$ROVER_ASR_MODEL_DIR/tokens.txt" ]] || fail 'ASR tokens.txt is missing'
compgen -G "$ROVER_ASR_MODEL_DIR/*encoder*.onnx" >/dev/null || fail 'ASR encoder model is missing'
compgen -G "$ROVER_ASR_MODEL_DIR/*decoder*.onnx" >/dev/null || fail 'ASR decoder model is missing'
compgen -G "$ROVER_ASR_MODEL_DIR/*joiner*.onnx" >/dev/null || fail 'ASR joiner model is missing'
[[ -d "$ROVER_TTS_MODEL_DIR" && -r "$ROVER_TTS_MODEL_DIR" ]] || fail 'TTS model directory is not readable'
if [[ "$tts_engine" == "pocket_tts" ]]; then
  tts_config="${ROVER_TTS_CONFIG:-$ROVER_TTS_MODEL_DIR/config.yaml}"
  [[ -f "$tts_config" && -r "$tts_config" ]] || fail 'Pocket TTS local config is not readable'
  ! grep -Eq '(^|[[:space:]])(hf|https?)://' "$tts_config" || fail 'Pocket TTS config contains a remote asset'
  [[ -n "${ROVER_TTS_CHECKPOINT:-}" ]] || fail 'ROVER_TTS_CHECKPOINT is not configured'
  [[ -n "${ROVER_TTS_VOICE_STATE:-}" ]] || fail 'ROVER_TTS_VOICE_STATE is not configured'
  [[ -f "$ROVER_TTS_CHECKPOINT" && -r "$ROVER_TTS_CHECKPOINT" ]] || fail 'Pocket TTS checkpoint is not readable'
  [[ -f "$ROVER_TTS_VOICE_STATE" && -r "$ROVER_TTS_VOICE_STATE" ]] || fail 'Pocket TTS voice state is not readable'
else
  [[ -f "$ROVER_TTS_MODEL_DIR/model.onnx" ]] || fail 'sherpa VITS model.onnx is missing'
  [[ -f "$ROVER_TTS_MODEL_DIR/lexicon.txt" ]] || fail 'sherpa VITS lexicon.txt is missing'
  [[ -f "$ROVER_TTS_MODEL_DIR/tokens.txt" ]] || fail 'sherpa VITS tokens.txt is missing'
fi
[[ -n "${ROVER_VOICE_GATEWAY_TOKEN:-}" ]] || fail 'gateway token is not configured'

python_bin="${ROVER_VOICE_PYTHON:-services/voice/.venv/bin/python}"
[[ -x "$python_bin" ]] || fail 'voice Python environment is unavailable'
if [[ -d "$ROVER_WAKEWORD_MODEL" ]]; then
  if [[ "$tts_engine" == "sherpa_vits" ]]; then
    "$python_bin" -c 'import numpy, sherpa_onnx' >/dev/null 2>&1 || fail 'voice runtime packages are unavailable (numpy/sherpa_onnx)'
  else
    "$python_bin" -c 'import numpy, pocket_tts, sherpa_onnx, yaml' >/dev/null 2>&1 || fail 'voice runtime packages are unavailable (numpy/pocket_tts/sherpa_onnx/yaml)'
  fi
else
  if [[ "$tts_engine" == "sherpa_vits" ]]; then
    "$python_bin" -c 'import numpy, openwakeword, sherpa_onnx' >/dev/null 2>&1 || fail 'voice runtime packages are unavailable (numpy/openwakeword/sherpa_onnx)'
  else
    "$python_bin" -c 'import numpy, openwakeword, pocket_tts, sherpa_onnx, yaml' >/dev/null 2>&1 || fail 'voice runtime packages are unavailable (numpy/openwakeword/pocket_tts/sherpa_onnx/yaml)'
  fi
fi

python3 - "${ROVER_VOICE_GATEWAY_URL:-http://127.0.0.1:8001/api/v1/voice}" <<'PY' || fail 'gateway must be loopback HTTP'
from urllib.parse import urlsplit
import sys
url = urlsplit(sys.argv[1])
if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}:
    raise SystemExit(1)
PY

printf '%s\n' 'voice prerequisites are available (no playback performed)'
