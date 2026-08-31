# Local Voice Runtime Runbook

The local service uses openWakeWord for the Chinese wake word, sherpa-onnx for offline ASR/VAD, and Piper for local TTS. Raw microphone audio stays on the host and is never sent to the API. The host service calls only the loopback gateway; it does not hold `ROVER_AI_API_KEY`, access ROS, or publish `/cmd_vel`.

Place externally supplied, licensed models under `/opt/jarvis-rover/models` and configure `ROVER_WAKEWORD_MODEL`, `ROVER_ASR_MODEL_DIR`, `ROVER_TTS_MODEL`, and `ROVER_TTS_CONFIG`. Missing assets are reported as unavailable; no model is downloaded automatically.

Create `/etc/jarvis-rover/runtime.env` (mode `0600`) with `ROVER_AI_BASE_URL`, `ROVER_AI_MODEL`, and `ROVER_AI_API_KEY`. Create `/etc/jarvis-rover/voice.env` (mode `0600`) with `ROVER_VOICE_GATEWAY_TOKEN`, stable `ROVER_VOICE_CAPTURE_DEVICE`, `ROVER_VOICE_PLAYBACK_DEVICE`, and model paths. The AI key must never be copied into `voice.env`. Rotate any key exposed during setup before enabling AI.

```bash
sudo systemctl enable --now rover-runtime.service
sudo systemctl enable --now jarvis-rover-voice.service
systemctl status jarvis-rover-voice.service --no-pager
journalctl -u jarvis-rover-voice.service -f
make voice-prerequisites
make voice-audio-test
sudo systemctl restart jarvis-rover-voice.service
sudo bash scripts/uninstall_rover_voice_service.sh
```

Voice failure never starts or resumes mapping, enables motion, invokes navigation/gimbal actions, publishes `/cmd_vel`, or executes arbitrary ROS commands. Use `arecord -l` and `aplay -l` for device names. Loopback `401` means token mismatch; `503` means the assistant is disabled/unavailable; stale heartbeats are shown in the web console.
