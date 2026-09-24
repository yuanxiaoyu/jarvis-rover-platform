# Pocket TTS Voice Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 mapping/safety 安全边界的前提下，为贾维斯小车接入宿主机本地 Pocket TTS 语音链路、受保护的 GPT voice gateway、确认式建图操作和真实健康状态，并完成离线与可用真机验证。

**Architecture:** `rover-voice.service` 独立运行在宿主机，使用 ALSA、openWakeWord、sherpa-onnx 和 Pocket TTS；它只把有界的本地 ASR 文本通过 loopback + 独立 token 发送给 FastAPI。FastAPI 负责 OpenAI-compatible provider、真实运行时上下文、结构化决策校验、确认状态和 mapping backend；语音服务不访问 ROS、不持有 GPT key、不发布 `/cmd_vel`。现有 ROS mapping/safety 迁移改动保持不回滚，缺少真实 ROS backend 时返回 unavailable 而不是模拟成功。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、httpx、pytest、Python `pocket-tts`、ALSA、openWakeWord、sherpa-onnx、ROS 2 Humble/rclpy、systemd、Vue 3/TypeScript、Docker。

**Spec:** `docs/superpowers/specs/2026-08-30-voice-assistant-integration-design.md`

## Global Constraints

- GPT provider 使用配置的 OpenAI-compatible base URL 和模型 `gpt-5.6`，真实 key 只从受保护 environment/secret 注入。
- `ROVER_AI_API_KEY` 与 `ROVER_VOICE_GATEWAY_TOKEN` 必须不同，key/token 不进入日志、前端、ROS 参数或语音服务。
- 唤醒词为“贾维斯”，唤醒、VAD、中文 ASR 和 TTS 的原始音频处理全部在本机完成；原始 PCM/WAV 不上传、不落盘。
- 语音服务只接受/发送有界文本和状态元数据；gateway 拒绝客户端提供的 action、ROS 名称、速度、shell 或 API key。
- 允许的 action 仅为 `mapping_start`、`mapping_pause`、`mapping_resume`、`mapping_save`、`mapping_stop`；每个 mapping action 必须经过同一 session 的明确二次确认和执行前状态复查。
- 任何移动、路径执行、云台、任意 ROS topic/service、shell 命令或 `/cmd_vel` 均不可由 GPT/语音直接执行。
- Pocket TTS checkpoint 与预计算 voice state 从项目外受保护目录加载；运行时不访问 Hugging Face 或其他网络源，不自动下载模型/voice/依赖。
- Pocket TTS 的中文发音必须通过固定 checkpoint/voice state 的普通话真机验收；voice cloning 不能自动视为中文模型支持，验收失败时显示 `tts_error`/`unavailable`。
- 没有真实设备、topic、模型、provider 或传感器数据时必须显示 `unavailable`/`stale`/`error`，不得使用 mock 回复、随机状态、静态音频或伪造成功。
- voice service 故障、断网、重启或停止不得阻止 runtime、mapping、safety 或 Web 控制台启动，也不得改变 motion permission 或发布速度。
- 单次录音最长 15 秒，唤醒后追问窗口 8 秒，GPT 并发 1、超时 20 秒、回复最多 512 tokens，TTS 队列最多一条，所有音频缓冲有界。
- 不提交真实 secret、私有模型二进制或未经许可的 voice/reference 音频。
- 本仓库已有的 staged mapping/runtime 删除和迁移变更不回滚；本计划只新增/修改实现语音需求所需文件。
- 不执行会让真实小车移动或改变建图状态的命令；真机验收只在人工明确授权后执行，并优先 dry-run/只读检查。

---

### Task 1: 建立 assistant/voice 领域模型和安全配置

**Files:**
- Modify: `services/api/app/config.py`
- Modify: `services/api/pyproject.toml`
- Replace: `services/api/app/models/voice.py`
- Create: `services/api/app/models/assistant.py`
- Test: `services/api/tests/test_assistant_models.py`
- Test: `services/api/tests/test_config_security.py`

**Interfaces:**
- Produces `VoiceAssistantRequest`, `MappingAction`, `AssistantDecision`, `AssistantError`, `VoiceAssistantResponse` and `VoiceStatus` from `app.models.assistant`.
- `VoiceAssistantRequest` fields are `schema_version: Literal[1]`, bounded `session_id`, `turn_id`, `transcript`, `language="zh-CN"`, nullable `confidence`, and `source: Literal["local-sherpa-onnx"]`.
- `MappingAction` exposes `type` from the five-action allowlist and optional `map_name`; only `mapping_save` may have a map name.
- `Settings.validate_assistant_configuration()` rejects enabled AI without key, invalid URL/limits, or equal AI and gateway secrets.

- [ ] **Step 1: Write failing model tests**

Add tests that assert:

```python
from pydantic import ValidationError
from app.models.assistant import MappingAction, VoiceAssistantRequest


def test_mapping_save_requires_safe_name():
    assert MappingAction(type="mapping_save", map_name="hall-01").map_name == "hall-01"
    for name in ("../map", "a/b", "a\\b", "", "bad name"):
        try:
            MappingAction(type="mapping_save", map_name=name)
        except ValidationError:
            pass
        else:
            raise AssertionError(name)


def test_request_rejects_untrusted_action_and_oversized_transcript():
    try:
        VoiceAssistantRequest(transcript="x", action="mapping_start")
    except ValidationError:
        pass
    else:
        raise AssertionError("client action must be rejected")
```

Also test forbidden extra fields, control characters, invalid confidence, invalid source, and IDs containing separators/control characters.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd services/api && python3 -m pytest tests/test_assistant_models.py tests/test_config_security.py -q`

Expected: FAIL because the new models/tests are not implemented.

- [ ] **Step 3: Implement bounded Pydantic models and settings**

Use `ConfigDict(extra="forbid")`, `Field(max_length=...)`, `Literal`, and validators. Define these exact states in `VoiceStatus`: `disabled`, `wake_listening`, `capturing`, `processing_asr`, `processing_assistant`, `speaking`, `audio_unavailable`, `asr_error`, `assistant_unavailable`, `tts_error`. Store secrets as `SecretStr | None`; never expose their values in model dumps or exception text. Add `httpx` to the API dependencies.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `cd services/api && python3 -m pytest tests/test_assistant_models.py tests/test_config_security.py -q`

Expected: PASS.

---

### Task 2: 实现 provider、决策验证和确认式 mapping service

**Files:**
- Create: `services/api/app/services/assistant_provider.py`
- Create: `services/api/app/services/assistant_service.py`
- Create: `services/api/app/services/mapping_backend.py`
- Create: `services/api/app/services/confirmation.py`
- Create: `services/api/app/models/mapping.py`
- Test: `services/api/tests/test_assistant_provider.py`
- Test: `services/api/tests/test_assistant_service.py`
- Test: `services/api/tests/test_mapping_backend.py`

**Interfaces:**
- `AssistantProvider` protocol: `async decide(transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision` and `async close() -> None`.
- `MappingBackend` protocol: `async status() -> MappingStatus`, `start(session_id)`, `pause()`, `resume()`, `save(map_name)`, `stop()`, and `close()`.
- `AssistantService(provider, mapping_backend, confirmation_ttl_seconds=15.0, transcript_max_chars=1000)` exposes `async handle(request) -> VoiceAssistantResponse`, `async status_context()`, and `async close()`.
- `PendingConfirmation` contains `session_id`, `turn_id`, `action`, and monotonic `expires_at`.
- A mapping backend that has no real ROS service returns/raises an explicit unavailable result; it must not claim that a map was created.

- [ ] **Step 1: Write failing provider tests**

Use an `httpx.MockTransport` to assert the provider posts to `<base_url>/chat/completions` with model `gpt-5.6`, bounded output, deterministic temperature, system safety instructions, and only bounded history/context. Cover success, timeout, 401, 429/5xx retry once, malformed JSON, unknown action, extra ROS fields, and secret non-disclosure.

- [ ] **Step 2: Write failing assistant-service tests**

Create fake provider/backend fixtures and assert:

```python
response = await service.handle(request("开始建图", session="s1", turn="t1"))
assert response.state == "awaiting_confirmation"
assert backend.calls == []

response = await service.handle(request("确认", session="s1", turn="t2"))
assert response.state in {"executed", "rejected", "unavailable"}
```

Cover cancellation, ambiguous follow-up, expired TTL, cross-session confirmation rejection, execution-time state change, ordinary question with `action is None`, unavailable mapping state, path traversal map names, and repeated/unknown backend results. Assert only real backend accepted/state/message can produce `executed`.

- [ ] **Step 3: Implement provider and local decision safety**

Parse the provider response as bounded JSON into `AssistantDecision`; reject unknown fields and any control field/phrase containing ROS, shell, URL, speed, `/cmd_vel`, movement, path execution or gimbal instructions. Permit plain text only when it is unambiguously an ordinary answer and set `action=None`; never infer an action from client input. Retry only requests that have not executed an action.

- [ ] **Step 4: Implement mapping status model, backend protocol and confirmation service**

Define `MappingState` (`idle`, `starting`, `mapping`, `paused`, `saving`, `error_recoverable`) and `MappingStatus` with `session_id`, `ready`, `motion_allowed`, `current_revision`, `last_error`. Validate action legality against the current state, re-read status immediately before confirmed execution, clear pending entries after every terminal outcome, and limit each session to one pending action.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: `cd services/api && python3 -m pytest tests/test_assistant_provider.py tests/test_assistant_service.py tests/test_mapping_backend.py -q`

Expected: PASS with no network request to the real provider.

---

### Task 3: 将 FastAPI voice gateway 接入真实服务状态和认证

**Files:**
- Modify: `services/api/app/routers/voice.py`
- Modify: `services/api/app/routers/__init__.py`
- Modify: `services/api/app/main.py`
- Create: `services/api/app/services/voice_status.py`
- Modify: `services/api/app/state.py`
- Test: `services/api/tests/test_voice_routes.py`
- Test: `services/api/tests/test_voice_integration.py`

**Interfaces:**
- `POST /api/v1/voice/assistant` accepts only `VoiceAssistantRequest`, requires loopback peer and `X-Rover-Voice-Token`, and returns `VoiceAssistantResponse`.
- `GET /api/v1/voice/status` returns `VoiceStatus`; stale heartbeat returns disabled/unavailable with a safe error.
- `POST /api/v1/voice/heartbeat` accepts authenticated `VoiceStatus` from the host service.
- Legacy mock `/voice/session` and `/voice/command` endpoints return HTTP 410 rather than silently executing mock behavior.
- `VoiceStatusStore(stale_seconds)` exposes `update(status)`, `current()`, `enqueue_tts(text)`, and `pop_tts()` with one-item bounded queue.

- [ ] **Step 1: Write failing route/auth tests**

Use FastAPI `TestClient` with an injected service/backend and assert the assistant endpoint rejects missing/wrong token, non-loopback client, action-bearing payloads and invalid source. Assert status returns stale/unavailable before the first heartbeat, fresh status after heartbeat, and no API key/token appears in response or log capture.

- [ ] **Step 2: Implement status store and secure routes**

Use `hmac.compare_digest` for token comparison. Do not accept raw audio, API keys, ROS fields or client action fields. Create provider/backend/service in the application lifespan only when configured; when dependencies are absent, leave the API alive and expose unavailable status. Do not initialize a mock provider or random sensor values for voice context.

- [ ] **Step 3: Wire the application lifespan**

Construct the configured OpenAI-compatible provider and `AssistantService`, register them on `app.state`, close owned clients on shutdown, and keep runtime startup independent from voice service startup. Ensure `GET /health` reports mapping/runtime availability without pretending voice is online.

- [ ] **Step 4: Run API tests**

Run: `cd services/api && python3 -m pytest -q`

Expected: all API tests PASS; tests use fakes and do not incur provider charges.

---

### Task 4: 实现宿主机音频适配器和 Pocket TTS

**Files:**
- Create: `services/voice/pyproject.toml`
- Create: `services/voice/rover_voice/__init__.py`
- Create: `services/voice/rover_voice/contracts.py`
- Create: `services/voice/rover_voice/config.py`
- Create: `services/voice/rover_voice/audio.py`
- Create: `services/voice/rover_voice/wakeword.py`
- Create: `services/voice/rover_voice/asr.py`
- Create: `services/voice/rover_voice/tts.py`
- Test: `services/voice/tests/test_adapters.py`
- Test: `services/voice/tests/test_deployment_config.py`
- Test: `services/voice/tests/test_privacy.py`

**Interfaces:**
- `VoiceConfig` loads `ROVER_VOICE_*`, `ROVER_WAKEWORD_PHRASE` (default `贾维斯`), `ROVER_WAKEWORD_MODEL`, `ROVER_ASR_MODEL_DIR`, `ROVER_TTS_MODEL_DIR`, `ROVER_TTS_CHECKPOINT`, `ROVER_TTS_VOICE_STATE`, `ROVER_TTS_DEVICE`, and `ROVER_TTS_PLAYBACK_SAMPLE_RATE`; `validate_prerequisites()` checks files/devices only when enabled.
- `PocketTtsPlayer(model_dir, checkpoint, voice_state, playback_device, device="cpu", playback_sample_rate=24000)` exposes `speak(text: str, stop_event) -> None` and terminates its worker/playback on interruption.
- `PocketTtsPlayer` uses the pinned `pocket_tts.TTSModel` API (`load_model`/`generate_audio`) behind the adapter, writes no intermediate audio file, and feeds bounded PCM/WAV data to `aplay`.
- `AlsaAudioInput`, `OpenWakeWordDetector`, and `SherpaOnnxRecognizer` each expose small fakeable methods and never upload or persist raw frames.

- [ ] **Step 1: Write failing adapter tests**

Test 16 kHz mono PCM16 validation, bounded frame buffering, missing model/checkpoint/voice state, missing `aplay`, empty text, one-item queue semantics, worker interruption, and that subprocess arguments contain no secrets. Inject fake Pocket TTS model and fake playback process; do not import the package or require ALSA in unit tests.

- [ ] **Step 2: Implement config and adapters**

Keep all optional heavy imports inside adapter construction so API/unit tests work without audio libraries. Probe ALSA read-only at startup; use stable configured device names instead of card numbers. Load checkpoint and precomputed `.safetensors` voice state from local paths, set CPU execution explicitly, obtain the model sample rate from the loaded model when available, and perform at most one configured resample before `aplay`.

- [ ] **Step 3: Add Chinese-language acceptance guard**

Record the pinned Pocket TTS package/checkpoint language coverage in the deployment metadata. The adapter may report `tts_error` when the target Mandarin voice state is absent or pronunciation validation has not passed; it must not silently substitute Piper, cloud TTS, a community model or canned audio.

- [ ] **Step 4: Run voice adapter tests**

Run: `cd services/voice && python3 -m pytest -q`

Expected: PASS without real microphone, speaker, model download or network access.

---

### Task 5: 实现 voice 状态机、gateway client 和 CLI 服务

**Files:**
- Create: `services/voice/rover_voice/state_machine.py`
- Create: `services/voice/rover_voice/service.py`
- Create: `services/voice/rover_voice/gateway_client.py`
- Create: `services/voice/rover_voice/cli.py`
- Test: `services/voice/tests/test_state_machine.py`
- Test: `services/voice/tests/test_end_to_end_fakes.py`

**Interfaces:**
- States are `DISABLED`, `WAKE_LISTENING`, `CAPTURING`, `PROCESSING_ASR`, `PROCESSING_ASSISTANT`, `SPEAKING`, `AUDIO_UNAVAILABLE`, `ASR_ERROR`, `ASSISTANT_UNAVAILABLE`, and `TTS_ERROR`.
- `StateMachine.transition(next_state)` rejects illegal transitions.
- `VoiceService(config, audio_input, wakeword, asr, tts, gateway)` exposes `process_frame(frame)`, `run_pending_once()`, `run()`, `stop()`, and `interrupt_speaking()`.
- `GatewayClient.assistant(request)` sends only transcript metadata; `GatewayClient.heartbeat(status)` sends status metadata using the gateway token.

- [ ] **Step 1: Write failing state and end-to-end fake tests**

Drive fake frames through wake hit → capture → VAD silence → ASR → assistant → Pocket TTS → follow-up timeout. Assert the 15-second cap, 8-second follow-up window, TTS interruption path, empty/low-confidence local prompt, bounded deque, no raw audio file, no provider key in client configuration, and restart clearing session/pending state.

- [ ] **Step 2: Implement deterministic state machine and service loop**

Use monotonic clocks, bounded `deque`, one pending async processing task, and a `threading.Event` for TTS interruption. Convert adapter exceptions to safe error codes/messages; never forward exception text that might contain secrets. A provider failure may speak a fixed local prompt only if Pocket TTS is healthy; a TTS failure leaves the gateway response observable and reports `tts_error`.

- [ ] **Step 3: Implement CLI construction and lifecycle**

`python -m rover_voice.cli` loads configuration, validates prerequisites, constructs the real adapters, starts the service, and exits nonzero with a visible unavailable reason on missing prerequisites. Keep a separate fake-injection path in tests; do not add a production mock mode or automatically play a tone.

- [ ] **Step 4: Run service tests**

Run: `cd services/voice && python3 -m pytest -q`

Expected: PASS with all hardware adapters replaced by fakes.

---

### Task 6: 部署配置、ROS 隔离和控制台状态

**Files:**
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `README.md`
- Modify: `ros2_ws/src/rover_voice_bridge/rover_voice_bridge/voice_bridge_node.py`
- Modify: `ros2_ws/src/rover_voice_bridge/params/voice_bridge.yaml`
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/types/contract.ts`
- Create: `apps/web/src/data/realSnapshot.ts`
- Create: `apps/web/src/lib/voiceClient.ts`
- Create: `deploy/jarvis-rover-voice.service`
- Create: `scripts/check_voice_prerequisites.sh`
- Create: `scripts/install_rover_voice_service.sh`
- Create: `scripts/uninstall_rover_voice_service.sh`
- Create: `scripts/test_voice_audio.sh`
- Create: `scripts/verify_voice_integration.sh`
- Test: `apps/web` TypeScript build and existing API tests

**Interfaces:**
- `.env.example` contains placeholders only and defaults voice/AI disabled.
- systemd service runs as restricted `rover` user with `DeviceAllow=/dev/snd/*`, read-only model directory and no `Requires=rover-runtime.service`; it may use `After=` and reconnect.
- `parseVoiceStatus(value: unknown): VoiceStatus` rejects unsupported schema/state/error/latency shapes; `fetchVoiceStatus()` reads `/api/v1/voice/status`.
- ROS `rover_voice_bridge` remains passive and does not hold the GPT key, call the voice gateway, publish arbitrary topics or publish `/cmd_vel`.

- [ ] **Step 1: Write deployment and web contract checks**

Assert required environment variable names, no secret literals, systemd ordering without `Requires`, no `/dev/snd` mapping into the runtime container, and TypeScript parsing of stale/error voice states. Assert the Web UI displays unavailable/stale rather than mock online status when the API is unreachable.

- [ ] **Step 2: Implement deployment files and scripts**

Use stable ALSA aliases and explicit local model paths. Prerequisite script checks devices, Python venv, package imports, checkpoint/voice state readability and loopback gateway configuration without sending GPT requests or executing mapping commands. Audio smoke script checks devices and model loading; playback/test tone requires an explicit `--play-test-tone` argument.

- [ ] **Step 3: Replace voice UI mock toggle with real status client**

Fetch initial snapshot/status from the API, subscribe to status updates or poll with bounded backoff, render `listening/capturing/processing/speaking/error/unavailable`, and make disconnected API state visibly stale. Do not synthesize transcript, confidence, battery, pose, map or voice success values in the real path.

- [ ] **Step 4: Keep ROS bridge passive and build the container**

Update only voice parameters/diagnostics needed for status; do not add external provider access to ROS YAML. Run `npm run build` and `docker compose config`; if Docker/ROS dependencies are unavailable, record the exact unavailable check rather than marking the rover healthy.

---

### Task 7: 完成自动化验证和安全验收报告

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-voice-assistant-integration-design.md` only if implementation findings require a precise correction
- Create: `docs/evidence/voice-acceptance-template.md`
- Test: `services/api/tests/`
- Test: `services/voice/tests/`

**Interfaces:**
- Verification must produce separate results for API/provider, voice fake pipeline, web build, ROS package/build, deployment config, and real hardware.
- A missing microphone, speaker, model, ROS service, network or key is recorded as `unavailable`/`unverified`, never `passed`.

- [ ] **Step 1: Run all offline tests**

Run:

```bash
cd services/api && python3 -m pytest -q
cd ../../services/voice && python3 -m pytest -q
cd ../../apps/web && npm run build
```

Expected: tests pass without real provider billing, model downloads or audio playback.

- [ ] **Step 2: Run static security and contract checks**

Run `git diff --check`, search changed voice files for legacy Piper/config references, inspect `docker compose config`, validate Python imports/compilation, and confirm no key, raw audio, mock transcript or static audio is committed. Check that no new code publishes `/cmd_vel` or invokes arbitrary ROS/shell commands from model output.

- [ ] **Step 3: Run safe runtime checks**

Start only the API in a local/test configuration with AI disabled and verify `/health`, `/api/v1/voice/status`, mapping/safety-independent startup and legacy endpoint behavior. If Docker/ROS tools exist, run read-only graph/package checks and launch with hardware command paths disabled; do not start navigation or send motion commands.

- [ ] **Step 4: Run authorized real-machine checks conditionally**

Only if the user has confirmed the physical devices and authorized playback, run read-only `arecord -l`/`aplay -l`, verify stable aliases, validate 16 kHz capture, load wakeword/ASR/Pocket TTS checkpoint and voice state, play one authorized test phrase, test wake/ASR/interrupt behavior, and inspect ROS graph for the unchanged safety boundary. Mapping state-changing commands require a separate explicit authorization and must be issued once with real status confirmation; otherwise record them as unverified.

- [ ] **Step 5: Report outcomes precisely**

Summarize passed, failed and unavailable checks with command output, distinguish simulated/fake tests from physical rover evidence, and state explicitly whether the rover was proven normal or only verified safe to start. Do not claim successful Chinese Pocket TTS or mapping unless the corresponding real acceptance evidence exists.
