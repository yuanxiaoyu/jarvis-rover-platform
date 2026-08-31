# Voice acceptance record

> Store completed records outside Git when they contain device inventory or operator details. Never attach raw audio, secrets, full prompts, full provider responses or persistent transcripts.

- Date/time (UTC):
- Checkout/commit:
- Operator authorization reference:
- Runtime unit state (`jarvis-rover-runtime.service`):
- Voice unit state (`jarvis-rover-voice.service`):

## Offline verification

- API/provider tests:
- Host voice adapter/state tests:
- Frontend build/typecheck:
- Static integration verification:
- Result and evidence path:

## Machine prerequisites

| Component | Configured identifier/path | Result | Evidence (safe summary only) |
| --- | --- | --- | --- |
| USB microphone / ALSA capture |  | live/unavailable |  |
| USB sound card / ALSA playback |  | live/unavailable |  |
| openWakeWord “你好贾维斯” model |  | loaded/unavailable |  |
| sherpa-onnx VAD/Chinese ASR |  | loaded/unavailable |  |
| Piper model/config |  | loaded/unavailable |  |
| Loopback gateway |  | reachable/unavailable |  |
| GPT-5.6 turn |  | authorized/not run/failed |  |

## Functional checks

- Wakeword detection stayed local:
- ASR transcript stayed local:
- Ordinary question and local Piper playback:
- Mapping command first turn requested confirmation without execution:
- Confirmed mapping command returned real backend result:
- Cancel/expiry/session isolation:
- Unsupported movement/path/gimbal/ROS/shell request rejected:

## Safety and isolation

- `/cmd_vel` publisher ownership before/after:
- Voice service start/stop/restart left mapping unchanged:
- Voice/network/model failure left safety unchanged:
- No raw audio files found:
- No provider key/token in logs or artifacts:
- Unverified items and follow-up:
