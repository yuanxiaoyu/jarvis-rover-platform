# Voice assistant acceptance evidence

> Fill this template with dated, authorized evidence. `unavailable` and
> `unverified` are valid outcomes; do not convert missing hardware or secrets
> into a pass.

## Run metadata

- Date/time (local and UTC):
- Operator / authorization reference:
- Git revision:
- Host and OS:

## Offline verification

| Area | Command / evidence | Result (`passed` / `failed` / `unavailable` / `unverified`) | Notes |
| --- | --- | --- | --- |
| API and provider fakes | `services/api` pytest |  |  |
| Voice fake pipeline | `services/voice` pytest |  |  |
| Web build | `apps/web` build |  |  |
| ROS package/build | read-only build or import check |  |  |
| Deployment config | compose/systemd/static checks |  |  |

## Runtime checks

- API health response (AI disabled is acceptable):
- Voice status before heartbeat:
- Voice status after heartbeat:
- Legacy voice endpoints return HTTP 410:
- Provider network/billing avoided:
- Secrets absent from logs and artifacts:

## Hardware checks (only with explicit playback authorization)

- Capture device and stable ALSA alias:
- Playback device and stable ALSA alias:
- 16 kHz mono PCM16 capture:
- Wake word model loaded:
- sherpa-onnx model loaded:
- Configured local TTS assets loaded (Pocket TTS or sherpa VITS):
- Mandarin pronunciation phrase and operator result:
- TTS interruption:
- Missing prerequisite behavior:

## Safety boundary

- ROS graph inspected without motion command:
- No `/cmd_vel` publication by voice service:
- No arbitrary ROS, shell, navigation, path, or gimbal action from assistant:
- Mapping action confirmation and execution-time status re-check:
- Any state-changing mapping check separately authorized? If not, mark it
  `unverified`.

## Summary

- Passed:
- Failed:
- Unavailable:
- Unverified:
- Conclusion: choose one of `proven safe to start`, `partially verified`, or
  `not accepted`. Do not claim Chinese TTS or real mapping success without
  the corresponding hardware evidence above.
