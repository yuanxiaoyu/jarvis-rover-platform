# Local Voice Runtime Runbook

## Scope and safety boundary

`jarvis-rover-voice.service` is an optional host process. It uses openWakeWord for “你好贾维斯”, sherpa-onnx for local Chinese VAD/ASR, and Piper for local TTS. Raw microphone audio remains in bounded memory and is never sent to the API or written to disk. The process calls only the loopback FastAPI gateway; it does not hold `ROVER_AI_API_KEY`, access ROS, publish topics, invoke mapping ROS services, or publish `/cmd_vel`.

The runtime service remains independent. Voice startup, shutdown, restart, network loss, model failure and audio failure must not start/resume mapping or change `motion_allowed`. Mapping changes from voice always require same-session confirmation and are executed through the existing mapping backend.

## Prerequisites

Use the repository checkout that owns the installed unit:

```bash
cd /home/jarvis-rover-platform
make voice-prerequisites
arecord -l
aplay -l
```

Use stable ALSA aliases or administrator-managed names, not `card 0`/`card 1`. Configure `ROVER_VOICE_CAPTURE_DEVICE` and `ROVER_VOICE_PLAYBACK_DEVICE` to those names. The service requires 16 kHz, mono, signed 16-bit little-endian PCM; `plughw` may provide format conversion.

Install the externally supplied and licensed model assets under `/opt/jarvis-rover/models`:

```text
/opt/jarvis-rover/models/
├── wakeword/nihao_javis.onnx
├── asr/<sherpa-onnx encoder, decoder, joiner, tokens and config files>
└── tts/<Piper zh-CN .onnx and matching .onnx.json>
```

Do not auto-download models from an unknown URL and do not commit model binaries. For every installed model, record source URL or supplier, version, license, SHA-256, file size and installation date in the machine-local asset inventory (outside Git). The wakeword model must actually detect “你好贾维斯”; a generic model is not an acceptable substitute.

## Secret and environment files

Create protected directories/files as root. Keep the GPT key only in the runtime environment and keep the gateway token separate:

```bash
sudo install -d -m 0750 /etc/jarvis-rover
sudo install -m 0600 /dev/null /etc/jarvis-rover/runtime.env
sudo install -m 0600 /dev/null /etc/jarvis-rover/voice.env
```

`runtime.env` contains the non-sensitive provider settings and `ROVER_AI_API_KEY`; `voice.env` contains `ROVER_VOICE_GATEWAY_TOKEN`, audio device aliases, model paths and voice settings. Never copy `ROVER_AI_API_KEY` into `voice.env`, the host voice virtualenv, ROS parameters, browser code, logs or this repository. The gateway token must not equal the provider key. The key previously exposed during setup must be revoked and regenerated before enabling the provider.

Useful non-secret variables are documented in `.env.example`. Environment precedence is explicit: process/systemd environment overrides the example; the host service does not read repository configuration files for secrets and does not read `.codex/config.toml`.

## Install and lifecycle

First ensure the runtime is healthy without starting mapping:

```bash
make runtime-prerequisites
sudo systemctl enable --now jarvis-rover-runtime.service
curl -fsS http://127.0.0.1:8000/health
```

Then install and enable voice only after model/device checks pass:

```bash
sudo bash scripts/install_rover_voice_service.sh --repo-dir "$(pwd)"
sudo systemctl enable --now jarvis-rover-voice.service
systemctl is-active jarvis-rover-voice.service
systemctl status jarvis-rover-voice.service --no-pager
journalctl -u jarvis-rover-voice.service -f
```

The unit is managed by the repository installer, runs as the low-privilege `rover`/`audio` identity, allows only `/dev/snd/*`, and has a read-only model checkout. It uses `After=jarvis-rover-runtime.service` without `Requires=`. If an unmanaged same-name unit exists, the installer must refuse to overwrite it.

Normal stop/restart is isolated:

```bash
sudo systemctl restart jarvis-rover-voice.service
sudo systemctl stop jarvis-rover-voice.service
sudo systemctl disable jarvis-rover-voice.service
sudo bash scripts/uninstall_rover_voice_service.sh
```

Uninstall removes only the managed unit. It does not delete maps, evidence, models, virtual environments or secret files, and does not run `docker compose down`.

## Verification and audio test

The normal service startup does not play a tone. Run the read-only check first:

```bash
make voice-prerequisites
make voice-audio-test
```

Only with explicit human approval to make sound, run:

```bash
bash scripts/test_voice_audio.sh --play-test-tone
```

The check must confirm capture/playback availability, model readability/loading and local Piper synthesis. It must not call GPT or any mapping endpoint. A missing device or model must produce `audio_unavailable`/`tts_error`; it must never create a static image, canned online state or simulated transcript.

## Expected conversation

After prerequisites pass, the initial state is `wake_listening`. Say “你好贾维斯”; the host performs wake detection, VAD and ASR locally. A recognized question sends only bounded transcript metadata to the loopback gateway. GPT returns a validated structured decision and Piper speaks only the returned bounded text. One wake activates an approximately eight-second follow-up window; speech during TTS interrupts playback and starts capture.

Mapping commands follow this sequence:

```text
“开始建图” → confirmation prompt; no backend call
“确认”     → re-read real mapping status → existing mapping backend
“取消”     → clear pending action; no backend call
```

The same confirmation policy applies to pause, resume, save and stop. A confirmation expires, cannot cross sessions or restarts, and cannot be reused. Voice requests for movement, path execution, navigation, gimbal/camera movement, shell commands, arbitrary ROS calls or AI configuration are rejected without a control call.

## Troubleshooting

- **`AUDIO_UNAVAILABLE` / no microphone:** run `arecord -l`, verify the configured stable alias, `rover` membership in `audio`, `/dev/snd` permissions and `journalctl -u jarvis-rover-voice.service`. Do not replace the device with an arbitrary card number.
- **No speaker / `TTS_ERROR`:** run `aplay -l`, verify the playback alias, then use the explicitly authorized audio test. Piper failure leaves text/gateway operation observable but does not fabricate spoken success.
- **Wakeword model error:** verify the configured ONNX file is readable, its recorded hash/license, and that it is the custom “你好贾维斯” model. The service remains unavailable instead of loading a fallback.
- **ASR error or empty transcript:** verify the complete sherpa-onnx model directory and compatible CPU build. Empty/low-confidence speech receives a local retry prompt and never reaches GPT.
- **Loopback `401`:** verify `ROVER_VOICE_GATEWAY_TOKEN` matches in runtime and voice files, without printing either file. Ensure the request peer is `127.0.0.1`/`::1`.
- **Loopback `503`:** inspect runtime health and `ROVER_AI_ENABLED`; verify the GPT key exists only in runtime, the base URL/model are correct, and the provider has not timed out. No mapping action is retried after an unknown result.
- **Stale voice heartbeat:** inspect `GET /api/v1/voice/status`, service status and journal. Restart only the voice unit; runtime/mapping/safety are independent.
- **Runtime/ROS issue:** use the existing runtime graph and mapping runbook. Do not disable bridge-required mode, start a second hardware container/agent/EKF/SLAM process, or bypass the safety gate to repair voice.

## Privacy and acceptance evidence

Allowed logs contain state transitions, component latency, opaque session/turn IDs, status classes and error categories. Logs must not contain PCM/WAV, authorization headers, provider keys, complete prompts/responses or default persistent transcripts. Check the journal and `/var/lib/jarvis-rover/voice` after testing.

Offline tests and static verification must pass before any real provider request. A true-machine acceptance record must separately state microphone, sound card, wakeword, ASR, Piper, provider, confirmation and safety-isolation results. Missing models/devices or an unperformed GPT turn are recorded as unverified/unavailable, never as passed.
