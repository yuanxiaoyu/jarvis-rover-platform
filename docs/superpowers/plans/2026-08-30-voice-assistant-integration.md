# Local “你好贾维斯” Voice Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在树莓派真机上实现“你好贾维斯”离线唤醒、离线中文 ASR、GPT-5.6 对话、本地 Piper TTS，并通过受保护的语音网关执行经过确认的建图操作。

**Architecture:** 宿主机 `rover-voice.service` 直接访问 USB 麦克风和 USB 声卡，使用 openWakeWord、sherpa-onnx VAD/ASR 与 Piper；它只把识别文本发送到本机 FastAPI voice gateway。`rover-runtime` 内部使用配置的 OpenAI-compatible GPT-5.6 provider 生成结构化决策，再由本地 schema、session confirmation、mapping 状态机和现有 `RosMappingBackend` 判定是否执行；绝不让 GPT 或语音进程直接访问 ROS 或 `/cmd_vel`。

**Tech Stack:** Python 3.10、FastAPI、Pydantic v2、httpx、ROS 2 Humble/rclpy bridge、openWakeWord、sherpa-onnx、Piper、ALSA、systemd、Vue 3/TypeScript、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-voice-assistant-integration-design.md`

## Global Constraints

- API 地址由 `ROVER_AI_BASE_URL` 配置，默认部署值为 `https://gmn.chuangzuoli.com/v1`；不得在代码中拼接未配置的 provider 路径。
- 模型 ID 使用 `ROVER_AI_MODEL=gpt-5.6`；不要改用其他模型或 OpenAI SDK shim。
- API key 只通过真机受保护的 secret/environment 注入；不得进入源代码、前端、ROS YAML、日志、测试 fixture、spec、plan 或 Git。
- `ROVER_AI_API_KEY` 与 `ROVER_VOICE_GATEWAY_TOKEN` 必须是两个不同的 secret。
- 唤醒词检测、VAD、中文 ASR 和 Piper TTS 全部在树莓派本地运行；原始麦克风音频不上传、不落盘。
- 语音服务使用 `16 kHz`、单声道、`signed 16-bit PCM little-endian`；音频缓冲、录音时长和 TTS 队列必须有界。
- 语音服务只调用 loopback voice gateway，不读取 ROS、不调用 ROS service、不发布 topic、不访问 `/cmd_vel`。
- GPT 只能返回 `none`、`mapping_start`、`mapping_pause`、`mapping_resume`、`mapping_save`、`mapping_stop` 六种决策；路径、移动、云台、shell、任意 ROS 命令和速度控制永远拒绝。
- 开始、暂停、恢复、保存和停止建图都必须经过同一 `session_id` 的明确确认、TTL 校验和执行前状态复查。
- `rover-voice.service` 不得使用 `Requires=rover-runtime.service`；语音故障不得影响 mapping、safety、systemd runtime 或最终 `/cmd_vel` publisher。
- 没有设备、模型、ROS 状态、GPT 网络或 TTS 时显示真实 `unavailable`/`stale`/`error`，不得回退到 mock 数据或伪造成功。
- 保留现有官方硬件容器 + `rover-runtime` 拓扑、`ROS_DOMAIN_ID=20`、唯一 safety `/cmd_vel` publisher 和 runtime 默认 `IDLE/motion_allowed=false`。
- 所有 provider 单元测试使用 fake provider，不产生真实 API 费用；真实 GPT 调用只在用户明确授权的真机验收步骤中执行。
- 每个任务完成后运行该任务列出的测试并创建一个独立提交；不要把 API key 或真机证据加入提交。

---

## 文件结构与职责

| 文件 | 职责 |
| --- | --- |
| `services/api/app/config.py` | 声明并校验 AI、voice gateway、assistant session 配置 |
| `services/api/app/models/assistant.py` | GPT 决策、mapping action、gateway request/response、错误和状态模型 |
| `services/api/app/services/assistant_provider.py` | OpenAI-compatible GPT-5.6 HTTP adapter protocol 和实现 |
| `services/api/app/services/assistant_service.py` | 最小真实上下文、决策校验、confirmation TTL、mapping backend 执行 |
| `services/api/app/services/voice_status.py` | 宿主机 voice heartbeat/status 的内存缓存和健康计算 |
| `services/api/app/routers/voice.py` | voice assistant、status、heartbeat 路由；移除 mock adapter 行为 |
| `services/api/app/main.py` | 创建/关闭 provider、assistant service 和 voice status store |
| `services/api/tests/test_assistant_provider.py` | provider response/error/secret 脱敏测试 |
| `services/api/tests/test_assistant_service.py` | 意图白名单、上下文、确认和 backend 执行测试 |
| `services/api/tests/test_voice_routes.py` | gateway 认证、路由响应、heartbeat/status 测试 |
| `services/voice/pyproject.toml` | 宿主机语音服务依赖和命令入口 |
| `services/voice/rover_voice/config.py` | 音频、模型、gateway、时间和资源配置 |
| `services/voice/rover_voice/contracts.py` | voice service 状态、ASR、assistant、TTS adapter 协议 |
| `services/voice/rover_voice/audio.py` | ALSA/PCM 输入输出适配和设备检查 |
| `services/voice/rover_voice/wakeword.py` | openWakeWord adapter 和阈值/冷却控制 |
| `services/voice/rover_voice/asr.py` | sherpa-onnx VAD/中文 ASR adapter |
| `services/voice/rover_voice/tts.py` | Piper stdout/ALSA 播放和打断 |
| `services/voice/rover_voice/gateway_client.py` | loopback voice gateway client 和 heartbeat |
| `services/voice/rover_voice/state_machine.py` | 明确语音状态机和有界会话逻辑 |
| `services/voice/rover_voice/service.py` | adapter 编排、唤醒循环、短会话、打断和降级 |
| `services/voice/rover_voice/cli.py` | prerequisite/运行入口和脱敏日志配置 |
| `services/voice/tests/test_state_machine.py` | 状态转移、VAD、短会话、打断、错误测试 |
| `services/voice/tests/test_adapters.py` | fake adapter 契约和配置测试 |
| `services/voice/tests/test_privacy.py` | 不写原始音频、不记录 secret 测试 |
| `deploy/jarvis-rover-voice.service` | 宿主机 systemd unit 模板 |
| `scripts/check_voice_prerequisites.sh` | 非破坏性设备、模型、权限和 runtime 检查 |
| `scripts/install_rover_voice_service.sh` | 安装/启用 voice systemd，不修改 mapping 数据 |
| `scripts/uninstall_rover_voice_service.sh` | 只卸载本项目 managed voice unit |
| `scripts/test_voice_audio.sh` | 人工授权的 ALSA/Piper/模型 smoke test |
| `apps/web/src/types/contract.ts` | 前端 voice status/assistant contract |
| `apps/web/src/lib/voiceClient.ts` | voice gateway/status HTTP client |
| `apps/web/src/App.vue` | 移除 voice panel 的本地 mock 行为并渲染真实状态 |
| `apps/web/src/lib/voiceClient.test.ts` | 前端 voice client 测试（如仓库测试工具已配置） |
| `.env.example` | 非敏感 AI/voice 配置名和占位说明 |
| `compose.yaml` | runtime 中传递非敏感 AI 配置和 secret 环境 |
| `Makefile` | voice check/install/uninstall/test 入口 |
| `README.md` | 真机 USB 音频、模型、secret 和服务运行手册 |

---

### Task 1: 建立服务端 voice/AI 配置和领域模型

**Files:**
- Modify: `services/api/app/config.py:4-20`
- Create: `services/api/app/models/assistant.py`
- Modify: `.env.example:1-20`
- Modify: `compose.yaml:10-30`
- Test: `services/api/tests/test_assistant_models.py`

**Interfaces:**
- Produces `AssistantSettings` fields exposed through existing `Settings`:
  `ai_enabled: bool`, `ai_base_url: str`, `ai_model: str`, `ai_api_key: str | None`, `ai_timeout_seconds: float`, `ai_max_output_tokens: int`, `voice_gateway_token: str | None`, `voice_transcript_max_chars: int`, `voice_confirmation_ttl_seconds: float`, `voice_followup_seconds: float`.
- Produces `MappingAction(type: Literal["mapping_start", "mapping_pause", "mapping_resume", "mapping_save", "mapping_stop"], map_name: str | None)`.
- Produces `AssistantDecision(reply_text: str, action: MappingAction | None, confidence: float | None)`.
- Produces `VoiceAssistantRequest(schema_version: int, session_id: str, turn_id: str, transcript: str, language: str, confidence: float | None, source: str)`.
- Produces `VoiceAssistantResponse(schema_version: int, session_id: str, turn_id: str, state: Literal["completed", "awaiting_confirmation", "executed", "rejected", "unavailable"], reply_text: str, action: MappingAction | None, error: AssistantError | None)`.
- Produces `VoiceStatus(state: Literal["disabled", "wake_listening", "capturing", "processing_asr", "processing_assistant", "speaking", "audio_unavailable", "asr_error", "assistant_unavailable", "tts_error"], enabled: bool, session_id: str | None, turn_id: str | None, last_error: AssistantError | None, component_latency_ms: dict[str, float | None])`.

- [ ] **Step 1: Write failing configuration tests**

```python
# services/api/tests/test_assistant_models.py
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models.assistant import MappingAction, VoiceAssistantRequest


def test_ai_settings_are_read_from_rover_environment(monkeypatch):
    monkeypatch.setenv("ROVER_AI_ENABLED", "true")
    monkeypatch.setenv("ROVER_AI_BASE_URL", "https://gmn.chuangzuoli.com/v1")
    monkeypatch.setenv("ROVER_AI_MODEL", "gpt-5.6")
    monkeypatch.setenv("ROVER_AI_API_KEY", "runtime-secret")

    settings = Settings(_env_file=None)

    assert settings.ai_enabled is True
    assert settings.ai_base_url == "https://gmn.chuangzuoli.com/v1"
    assert settings.ai_model == "gpt-5.6"
    assert settings.ai_api_key == "runtime-secret"


def test_mapping_action_rejects_unknown_action():
    with pytest.raises(ValidationError):
        MappingAction(type="cmd_vel", map_name=None)


def test_voice_request_rejects_non_local_source():
    with pytest.raises(ValidationError):
        VoiceAssistantRequest(
            schema_version=1,
            session_id="voice-1",
            turn_id="turn-1",
            transcript="状态",
            language="zh-CN",
            confidence=0.9,
            source="cloud-asr",
        )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd services/api && pytest tests/test_assistant_models.py -v`

Expected: FAIL because the new settings and models do not exist.

- [ ] **Step 3: Add settings with explicit secret and bounds validation**

Add fields to `Settings` and keep `SettingsConfigDict(env_prefix="ROVER_", env_file=".env", extra="ignore")`. Validate enabled AI configuration in a method named `validate_assistant_configuration()`:

```python
def validate_assistant_configuration(self) -> None:
    if not self.ai_enabled:
        return
    if not self.ai_api_key:
        raise ValueError("ROVER_AI_API_KEY is required when ROVER_AI_ENABLED=true")
    if not self.ai_base_url.startswith(("http://", "https://")):
        raise ValueError("ROVER_AI_BASE_URL must use http or https")
    if self.ai_timeout_seconds <= 0 or self.ai_max_output_tokens < 1:
        raise ValueError("assistant timeout and output limit must be positive")
```

Use `SecretStr` for `ai_api_key` and `voice_gateway_token` so their `repr()` and Pydantic serialization never expose values. Keep the runtime default `ai_enabled=False` until the real secret is provisioned.

- [ ] **Step 4: Add the exact Pydantic models and deterministic validators**

Implement bounded strings, `confidence` range `0..1`, `schema_version == 1`, `source == "local-sherpa-onnx"`, and action-specific `map_name`. Reject `/`, `\\`, `..`, control characters and empty names for `mapping_save`. Set ordinary assistant decisions to `action=None`; do not add free-form ROS fields to any model.

- [ ] **Step 5: Add the non-secret example variables and Compose pass-through**

Append to `.env.example`:

```text
ROVER_AI_ENABLED=false
ROVER_AI_BASE_URL=https://gmn.chuangzuoli.com/v1
ROVER_AI_MODEL=gpt-5.6
ROVER_AI_API_KEY=
ROVER_AI_TIMEOUT_SECONDS=20
ROVER_AI_MAX_OUTPUT_TOKENS=512
ROVER_VOICE_GATEWAY_TOKEN=
ROVER_VOICE_TRANSCRIPT_MAX_CHARS=1000
ROVER_VOICE_CONFIRMATION_TTL_SECONDS=15
ROVER_VOICE_FOLLOWUP_SECONDS=8
```

Pass these variables into `rover-runtime` in `compose.yaml`; do not add a literal key. Use the existing `.env`/systemd secret-file mechanism and document `0600` permissions in the next task.

- [ ] **Step 6: Run focused tests and commit**

Run: `cd services/api && pytest tests/test_assistant_models.py -v`

Expected: PASS.

```bash
git add services/api/app/config.py services/api/app/models/assistant.py services/api/tests/test_assistant_models.py .env.example compose.yaml
git commit -m "feat: add voice assistant contracts"
```

---

### Task 2: Implement the GPT-5.6 OpenAI-compatible provider adapter

**Files:**
- Create: `services/api/app/services/assistant_provider.py`
- Create: `services/api/tests/test_assistant_provider.py`
- Modify: `services/api/pyproject.toml:7-18`

**Interfaces:**
- Produces protocol:
  `class AssistantProvider(Protocol): async def decide(self, transcript: str, context: dict[str, object], history: list[dict[str, str]]) -> AssistantDecision: ...`
- Produces `OpenAICompatibleAssistantProvider(base_url: str, api_key: SecretStr, model: str, timeout_seconds: float, max_output_tokens: int, transport: httpx.AsyncClient | None = None)`.
- Provider must send `POST {base_url}/chat/completions` only when the configured base URL ends in `/v1`; if the configured value already ends in `/chat/completions`, use it as-is. Do not silently discover or call another host/path.
- Provider must strip secrets from raised/logged errors and translate provider failures to `AssistantProviderError(code, message, recoverable)`.

- [ ] **Step 1: Add httpx and write fake-transport tests**

Add `httpx>=0.27.0` to runtime dependencies if it is not already installed outside the dev group. Write tests using `httpx.MockTransport`:

```python
@pytest.mark.anyio
async def test_provider_sends_gpt_model_and_structured_instruction():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": '{"reply_text":"当前为空闲。","action":null,"confidence":0.98}'
                    }
                }]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleAssistantProvider(
        base_url="https://gmn.chuangzuoli.com/v1",
        api_key=SecretStr("runtime-secret"),
        model="gpt-5.6",
        timeout_seconds=2,
        max_output_tokens=128,
        transport=client,
    )

    decision = await provider.decide("当前状态？", {"mapping": {"state": "idle"}}, [])

    assert decision.action is None
    assert requests[0].url == "https://gmn.chuangzuoli.com/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer runtime-secret"
    assert requests[0].json()["model"] == "gpt-5.6"
```

Also test invalid JSON, missing `choices`, HTTP 401/429/500, timeout, action `cmd_vel`, overlong reply, and an exception string containing the key. Assert the key is absent from `str(exc)`, logs and response models.

- [ ] **Step 2: Run provider tests and verify they fail**

Run: `cd services/api && pytest tests/test_assistant_provider.py -v`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement request construction and bounded response parsing**

Use `httpx.AsyncClient` with explicit connect/read/write/pool timeout. Send a Chinese system message containing the six-action allowlist and the prohibition on ROS/shell/speed output. Send only the transcript, minimum real context and bounded history. Request `max_tokens` from configured settings. Parse only `choices[0].message.content`; accept a fenced JSON object only after removing the surrounding markdown fence, then validate with `AssistantDecision.model_validate_json`.

Do not use `openai` package or an OpenAI shim. The endpoint is explicitly OpenAI-compatible and the project should own only the small HTTP adapter needed here.

- [ ] **Step 4: Add local security validation after provider parsing**

Reject any candidate with unknown fields, non-null action outside the six mapping types, a `map_name` on non-save actions, forbidden substrings representing ROS/topic/service/shell/speed control, empty or overlong `reply_text`, or an invalid confidence. Return `AssistantProviderError(code="invalid_decision", recoverable=False)` without retrying.

- [ ] **Step 5: Add retry policy without duplicate side effects**

Retry at most once for connection timeout, 429 or 5xx while still inside the provider call. Never retry mapping actions after the gateway begins backend execution. Do not log request body, authorization header or complete provider response; log only elapsed time, status class and an opaque request ID generated locally.

- [ ] **Step 6: Run tests and commit**

Run: `cd services/api && pytest tests/test_assistant_provider.py -v`

Expected: PASS.

```bash
git add services/api/app/services/assistant_provider.py services/api/tests/test_assistant_provider.py services/api/pyproject.toml
git commit -m "feat: add gpt assistant provider"
```

---

### Task 3: Add assistant orchestration, real mapping context, and confirmation state

**Files:**
- Create: `services/api/app/services/assistant_service.py`
- Create: `services/api/tests/test_assistant_service.py`
- Modify: `services/api/app/services/mapping_backend.py:15-31` only if a read-only context protocol is needed

**Interfaces:**
- Produces `AssistantService(provider: AssistantProvider, mapping_backend: MappingBackend, confirmation_ttl_seconds: float, transcript_max_chars: int)`.
- Produces `async def handle(self, request: VoiceAssistantRequest) -> VoiceAssistantResponse`.
- Produces `async def status_context(self) -> dict[str, object]`.
- Produces `async def close(self) -> None`.
- Uses an in-memory `PendingConfirmation(session_id, turn_id, action, expires_at)` store with at most one pending action per session.

- [ ] **Step 1: Write service tests with a fake provider and InMemoryMappingBackend**

```python
@pytest.mark.anyio
async def test_mapping_command_requires_confirmation_and_does_not_execute_first_turn():
    provider = FakeProvider(
        AssistantDecision(
            reply_text="当前为空闲，是否确认开始建图？",
            action=MappingAction(type="mapping_start"),
            confidence=0.95,
        )
    )
    backend = InMemoryMappingBackend()
    service = AssistantService(provider, backend, confirmation_ttl_seconds=15, transcript_max_chars=1000)

    first = await service.handle(request("开始建图", session_id="voice-1", turn_id="turn-1"))

    assert first.state == "awaiting_confirmation"
    assert (await backend.status()).state.value == "idle"
```

Add tests for explicit `确认` execution, `取消`, expiry, different session rejection, pending replacement, mapping status conflict, save requiring a valid name, ordinary query with `action=None`, unavailable mapping backend, no real sensor fields being filled, and rejected requests for movement/path/gimbal/shell.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `cd services/api && pytest tests/test_assistant_service.py -v`

Expected: FAIL because `AssistantService` does not exist.

- [ ] **Step 3: Build the minimum real context**

`status_context()` must call `await mapping_backend.status()` on every assistant turn and serialize only real values:

```python
{
    "mapping": {
        "session_id": status.session_id,
        "state": status.state.value,
        "ready": status.ready,
        "motion_allowed": status.motion_allowed,
        "current_revision": status.current_revision,
        "last_error": status.last_error,
    },
    "sources": {
        "map": {"state": "unavailable", "reason": "voice context source not connected"},
        "scan": {"state": "unavailable", "reason": "voice context source not connected"},
        "camera": {"state": "unavailable", "reason": "voice context source not connected"},
    },
    "capabilities": {
        "mapping_actions": ["start", "pause", "resume", "save", "stop"],
        "motion": False,
        "path": False,
        "gimbal": False,
    },
}
```

Do not import `app.services.mock_data`, `MISSION_STATE`, `TASK_STATE` or any front-end seed data. If the backend raises `RuntimeError`/`TimeoutError`, return `unavailable` with a safe Chinese message.

- [ ] **Step 4: Implement deterministic confirmation before provider calls**

On a transcript received while a non-expired pending action exists, check normalized Chinese confirmation/cancellation terms locally. Only `确认`/`是`/`执行`/`好的` and `取消`/`否`/`不要`/`停止操作` are accepted as deterministic decisions. Ambiguous text must not execute; return `awaiting_confirmation` with a request for an explicit confirmation. Confirmation execution must:

```python
current = await self._mapping_backend.status()
self._validate_action_against_state(pending.action, current)
result = await self._execute_action(pending.action)
```

Clear pending state on execution, cancellation, expiry, session mismatch or backend result. Never retry an action with unknown result.

- [ ] **Step 5: Implement provider turn and action validation**

For a new transcript, call provider with `status_context()` and bounded in-memory history. If the decision has no action, return `completed`. If it has a mapping action, validate against current `MappingStatus` and save-name rules, store exactly one pending action, and return `awaiting_confirmation`. If it requests motion/path/gimbal/ROS/shell, return `rejected` and do not call backend.

- [ ] **Step 6: Run tests and commit**

Run: `cd services/api && pytest tests/test_assistant_service.py -v`

Expected: PASS.

```bash
git add services/api/app/services/assistant_service.py services/api/tests/test_assistant_service.py services/api/app/services/mapping_backend.py
git commit -m "feat: add safe voice assistant orchestration"
```

---

### Task 4: Replace mock voice routes with authenticated assistant gateway and status heartbeat

**Files:**
- Create: `services/api/app/services/voice_status.py`
- Modify: `services/api/app/routers/voice.py:1-58`
- Modify: `services/api/app/main.py:1-92`
- Modify: `services/api/app/models/voice.py:1-27`
- Create: `services/api/tests/test_voice_routes.py`

**Interfaces:**
- Produces `VoiceStatusStore.update(status: VoiceStatus) -> None` and `VoiceStatusStore.current() -> VoiceStatus`.
- Produces `POST /api/v1/voice/assistant` using `X-Rover-Voice-Token`.
- Produces `GET /api/v1/voice/status` for read-only status.
- Produces `POST /api/v1/voice/heartbeat` using the same token, accepting `VoiceStatus` from loopback voice service.
- Existing `/api/v1/voice/session` and `/api/v1/voice/command` must no longer mutate mock adapter/task state; either delegate to the new service with explicit deprecation response or return a documented `410` response. The chosen behavior must be covered by tests and must not create a task from an unvalidated client-provided intent.

- [ ] **Step 1: Write route tests before replacing the router**

Use `TestClient` with an injected fake `AssistantService` and a configured token:

```python
def test_voice_assistant_requires_loopback_and_token():
    with client_with_assistant(token="gateway-secret") as client:
        response = client.post(
            "/api/v1/voice/assistant",
            headers={"X-Rover-Voice-Token": "wrong"},
            json=voice_request_json(),
        )

    assert response.status_code == 401


def test_voice_assistant_returns_real_service_decision():
    with client_with_assistant(token="gateway-secret") as client:
        response = client.post(
            "/api/v1/voice/assistant",
            headers={"X-Rover-Voice-Token": "gateway-secret"},
            json=voice_request_json(transcript="当前建图状态？"),
        )

    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["action"] is None
```

Test peer host rejection by setting a non-loopback client in the request fixture, token timing-safe comparison, malformed requests, heartbeat update, status retrieval, assistant unavailable, and legacy route behavior.

- [ ] **Step 2: Run route tests and verify they fail**

Run: `cd services/api && pytest tests/test_voice_routes.py -v`

Expected: FAIL because the authenticated gateway and status store do not exist.

- [ ] **Step 3: Add token/peer authentication dependency**

Implement a dependency that checks `request.client.host in {"127.0.0.1", "::1"}` and compares `X-Rover-Voice-Token` to `settings.voice_gateway_token.get_secret_value()` with `hmac.compare_digest`. If the token is unset or peer is not loopback, return `401` without disclosing which check failed. Never accept a token from JSON or query parameters.

- [ ] **Step 4: Wire the assistant service into application lifespan**

When `settings.ai_enabled` is true, call `settings.validate_assistant_configuration()`, construct `OpenAICompatibleAssistantProvider`, obtain the already initialized mapping backend, and store `application.state.assistant_service`. Do not create an `InMemoryMappingBackend` in production when `ROVER_ROS_BRIDGE_REQUIRED=true`. Close the provider HTTP client and assistant service on shutdown. Keep existing test injection behavior when `app.state.assistant_service` is pre-populated.

When AI is disabled, the route must return `503` with `assistant_unavailable`; it must not return a fake answer.

- [ ] **Step 5: Implement voice status heartbeat and remove mock behavior**

Store only the latest status and received time in memory. Mark status stale after `ROVER_VOICE_STATUS_STALE_SECONDS` and return `unavailable` after the heartbeat expires. Replace `VOICE_STATE.adapter="mock"` and the transcript mutation logic. Do not append to `TASK_STATE` from voice input. Keep any compatibility route explicitly read-only or delegated through `AssistantService`.

- [ ] **Step 6: Run API regression and commit**

Run: `cd services/api && pytest -q`

Expected: all existing mapping/API tests plus the new voice tests PASS.

```bash
git add services/api/app/routers/voice.py services/api/app/main.py services/api/app/models/voice.py services/api/app/services/voice_status.py services/api/tests/test_voice_routes.py
git commit -m "feat: add authenticated voice gateway"
```

---

### Task 5: Create the host voice service contracts and dependency-isolated adapters

**Files:**
- Create: `services/voice/pyproject.toml`
- Create: `services/voice/rover_voice/__init__.py`
- Create: `services/voice/rover_voice/contracts.py`
- Create: `services/voice/rover_voice/config.py`
- Create: `services/voice/rover_voice/audio.py`
- Create: `services/voice/rover_voice/wakeword.py`
- Create: `services/voice/rover_voice/asr.py`
- Create: `services/voice/rover_voice/tts.py`
- Create: `services/voice/tests/test_adapters.py`

**Interfaces:**
- `AudioInput.start() -> AsyncIterator[bytes]`, `AudioInput.close() -> None`.
- `AudioOutput.play_pcm(stream: AsyncIterator[bytes], stop_event: threading.Event) -> None`, `AudioOutput.close() -> None`.
- `WakeWordDetector.process(frame: bytes) -> bool`.
- `SpeechRecognizer.transcribe(frames: list[bytes]) -> AsrResult(text: str, confidence: float | None, duration_ms: int)`.
- `SpeechRecognizer.is_speech(frame: bytes) -> bool`.
- `TtsPlayer.speak(text: str, stop_event: threading.Event) -> None`.
- `GatewayClient.assistant(request: VoiceAssistantRequest) -> VoiceAssistantResponse` and `GatewayClient.heartbeat(status: VoiceStatus) -> None`.
- Every hardware implementation must have a fake implementation for tests; importing the package must not open ALSA or load a model.

- [ ] **Step 1: Write adapter contract tests with fake implementations**

Test `VoiceConfig` rejects absent model paths when enabled, rejects non-16-kHz configuration, bounds max recording seconds and queue size, and never includes `ai_api_key`. Test fake wakeword/ASR/TTS adapters satisfy the protocols. Test a no-op construction does not touch `/dev/snd`.

- [ ] **Step 2: Run tests and verify they fail**

Run: `cd services/voice && pytest -q`

Expected: FAIL because the service package and adapters do not exist.

- [ ] **Step 3: Implement configuration from environment**

Use a dedicated Pydantic settings class without the `ROVER_` prefix ambiguity by mapping the exact names explicitly. Required values when enabled:

```text
ROVER_VOICE_ENABLED
ROVER_VOICE_CAPTURE_DEVICE
ROVER_VOICE_PLAYBACK_DEVICE
ROVER_WAKEWORD_MODEL
ROVER_ASR_MODEL_DIR
ROVER_TTS_MODEL
ROVER_TTS_CONFIG
ROVER_VOICE_GATEWAY_URL=http://127.0.0.1:8000/api/v1/voice
ROVER_VOICE_GATEWAY_TOKEN
ROVER_VOICE_SAMPLE_RATE=16000
ROVER_VOICE_CHANNELS=1
ROVER_VOICE_RECORD_MAX_SECONDS=15
ROVER_VOICE_FOLLOWUP_SECONDS=8
ROVER_VOICE_VAD_SILENCE_MS
ROVER_WAKEWORD_THRESHOLD
ROVER_WAKEWORD_COOLDOWN_SECONDS
```

Validate `sample_rate == 16000`, `channels == 1`, positive timeouts, an absolute gateway URL on loopback, and non-empty model paths. Never accept `ROVER_AI_API_KEY` in this service configuration.

- [ ] **Step 4: Implement lazy ALSA adapters and device probes**

Use stable ALSA names supplied by configuration, not card numbers. `probe_capture_device()` and `probe_playback_device()` must return structured errors and never write audio. Capture converts to PCM16 mono 16 kHz; playback accepts PCM bytes and terminates on a stop event. Keep device-opening imports and calls inside adapter methods so unit tests can use fakes.

- [ ] **Step 5: Implement lazy model adapters**

`OpenWakeWordDetector` loads exactly the configured custom model and exposes threshold/cooldown. `SherpaOnnxRecognizer` loads configured VAD/ASR model files and returns bounded text/confidence. `PiperTtsPlayer` starts Piper with configured model/config and pipes raw PCM to the configured ALSA output; kill the process group on interruption. Missing or invalid model files raise typed prerequisite errors, not fallback models.

- [ ] **Step 6: Implement loopback gateway client and heartbeat**

Use `httpx.AsyncClient` only for `http://127.0.0.1:8000`; send `X-Rover-Voice-Token`. Retry heartbeat with bounded backoff, but do not retry assistant actions after a response with unknown execution result. Do not log request JSON or token. Map `503`, `401`, timeout and malformed response to typed `assistant_unavailable` errors.

- [ ] **Step 7: Run adapter tests and commit**

Run: `cd services/voice && pytest -q`

Expected: PASS using only fake adapters and temporary test files.

```bash
git add services/voice/pyproject.toml services/voice/rover_voice services/voice/tests/test_adapters.py
git commit -m "feat: add local voice adapter layer"
```

---

### Task 6: Implement the local voice state machine and short-session loop

**Files:**
- Create: `services/voice/rover_voice/state_machine.py`
- Create: `services/voice/rover_voice/gateway_client.py`
- Create: `services/voice/rover_voice/service.py`
- Create: `services/voice/rover_voice/cli.py`
- Create: `services/voice/tests/test_state_machine.py`
- Create: `services/voice/tests/test_privacy.py`

**Interfaces:**
- Produces `VoiceRuntime(state: VoiceState, session_id: str | None, turn_id: str | None, last_error: AssistantError | None)`.
- Produces `VoiceService.run() -> None`, `VoiceService.stop() -> None`.
- Produces `VoiceService.process_frame(frame: bytes) -> None` for deterministic test driving.
- Produces `VoiceService.transition(next_state: VoiceState) -> None`.
- Uses states exactly: `DISABLED`, `WAKE_LISTENING`, `CAPTURING`, `PROCESSING_ASR`, `PROCESSING_ASSISTANT`, `SPEAKING`, `AUDIO_UNAVAILABLE`, `ASR_ERROR`, `ASSISTANT_UNAVAILABLE`, `TTS_ERROR`.

- [ ] **Step 1: Write deterministic state transition tests**

```python
def test_wake_to_capture_to_asr_to_assistant_to_speaking_to_followup():
    service = service_with_fakes()

    service.enable()
    assert service.runtime.state == VoiceState.WAKE_LISTENING
    service.fake_wake.detect_next = True
    service.process_frame(pcm_frame())
    assert service.runtime.state == VoiceState.CAPTURING
    service.fake_vad.end_after_next = True
    service.process_frame(pcm_frame())
    assert service.runtime.state == VoiceState.PROCESSING_ASR
    service.run_pending_once()
    assert service.runtime.state == VoiceState.PROCESSING_ASSISTANT
    service.run_pending_once()
    assert service.runtime.state == VoiceState.SPEAKING
```

Add tests for 15-second recording limit, empty/low-confidence ASR, 8-second follow-up timeout, TTS interruption, bounded one-item queue, missing device/model, gateway timeout, service stop, and no pending action restoration after restart.

- [ ] **Step 2: Run tests and verify they fail**

Run: `cd services/voice && pytest tests/test_state_machine.py -q`

Expected: FAIL because the state machine and service do not exist.

- [ ] **Step 3: Implement explicit state transitions**

Reject invalid transitions rather than silently combining booleans. On wakeword hit create a cryptographically random or UUID session ID and a new turn ID for each ASR submission. Keep audio frames in a bounded deque; clear them after ASR. On service startup never set a pending action.

- [ ] **Step 4: Implement capture, VAD and local ASR**

After wakeword detection, collect frames until VAD reports silence or 15 seconds elapse. Run sherpa-onnx locally; if transcript is empty or confidence is below configured threshold, invoke Piper with a fixed local prompt and return to follow-up/listening without gateway call. Do not write WAV/PCM files.

- [ ] **Step 5: Implement assistant request, TTS and interruption**

Send only `VoiceAssistantRequest` text metadata to the gateway. On a response, invoke Piper with bounded `reply_text`. During playback, run a low-cost VAD watcher; set `stop_event`, terminate current Piper process group, discard queued audio, and move to `CAPTURING`. After playback enter an 8-second follow-up timer; then return to `WAKE_LISTENING`.

- [ ] **Step 6: Implement status heartbeat and privacy-safe logging**

Post status transitions to `/heartbeat` with a bounded cadence. Log state, elapsed times, opaque session/turn IDs and error categories only. Add a `RedactingFilter` that removes gateway token, any configured AI key if accidentally present in an exception, and authorization header patterns. The privacy test must assert no raw frame bytes are written to files or logs.

- [ ] **Step 7: Add CLI and clean shutdown**

`python -m rover_voice.cli run` loads configuration, checks prerequisites, constructs real adapters and handles SIGTERM/SIGINT. It must exit nonzero for missing required wakeword/ASR/TTS models or devices, while systemd restarts it. It must not execute mapping commands on startup or shutdown.

- [ ] **Step 8: Run tests and commit**

Run: `cd services/voice && pytest -q`

Expected: PASS.

```bash
git add services/voice/rover_voice/state_machine.py services/voice/rover_voice/gateway_client.py services/voice/rover_voice/service.py services/voice/rover_voice/cli.py services/voice/tests/test_state_machine.py services/voice/tests/test_privacy.py
git commit -m "feat: add local voice conversation loop"
```

---

### Task 7: Add model/device prerequisite checks and systemd deployment

**Files:**
- Create: `deploy/jarvis-rover-voice.service`
- Create: `scripts/check_voice_prerequisites.sh`
- Create: `scripts/install_rover_voice_service.sh`
- Create: `scripts/uninstall_rover_voice_service.sh`
- Create: `scripts/test_voice_audio.sh`
- Modify: `Makefile:1-100`
- Create: `services/voice/tests/test_deployment_config.py`

**Interfaces:**
- `check_voice_prerequisites.sh` is read-only by default; it must not start/stop containers, alter systemd, publish ROS, or call GPT.
- Installer accepts `--repo-dir`, `--env-file`, `--voice-env-file`; it installs only a unit marked `Managed-By: jarvis-rover-voice-installer`.
- Uninstaller refuses to remove an unmanaged same-name unit and never deletes models, maps, evidence, virtualenvs or secrets.
- `test_voice_audio.sh` requires explicit `--play-test-tone` for playback and never calls mapping commands.

- [ ] **Step 1: Write shell contract tests**

Use a temporary fake `systemctl`, `arecord`, `aplay`, model directory and repo to verify:

```text
checker with missing microphone -> nonzero and AUDIO_UNAVAILABLE message
checker with missing wake model -> nonzero and model path message
installer with unmanaged unit -> refuses without overwrite
installer with managed unit -> renders repo path and enables unit
uninstaller with unmanaged unit -> refuses
```

Also assert generated unit contains `After=rover-runtime.service`, no `Requires=rover-runtime.service`, `DeviceAllow=/dev/snd/*`, and no mapping command.

- [ ] **Step 2: Run deployment tests and verify they fail**

Run: `cd services/voice && pytest tests/test_deployment_config.py -q`

Expected: FAIL because scripts and unit do not exist.

- [ ] **Step 3: Implement prerequisite checker**

Check systemd, Python environment, `arecord`/`aplay`, stable configured device names, model files, permissions, `ROVER_VOICE_GATEWAY_TOKEN`, loopback gateway health and the existing runtime health endpoint. Do not perform a real GPT call. Return a concise failure summary and avoid printing secret values.

- [ ] **Step 4: Implement the managed unit**

Use a unit shaped like:

```ini
[Unit]
Description=Jarvis Rover local voice assistant
After=network-online.target rover-runtime.service
Wants=network-online.target

[Service]
Type=simple
User=rover
Group=audio
SupplementaryGroups=audio
EnvironmentFile=-/etc/jarvis-rover/voice.env
WorkingDirectory=@REPO_DIR@/services/voice
ExecStart=@REPO_DIR@/.venv-voice/bin/python -m rover_voice.cli run
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/jarvis-rover/voice
ReadOnlyPaths=@REPO_DIR@/models
DeviceAllow=/dev/snd/*
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
```

The installer must render `@REPO_DIR@`, create only `/var/lib/jarvis-rover/voice`, preserve existing unmanaged units by refusing overwrite, set secret file mode `0600`, run `systemctl daemon-reload`, and `enable --now` only after all checks pass.

- [ ] **Step 5: Implement smoke script and Makefile targets**

Add:

```make
voice-prerequisites:
	bash scripts/check_voice_prerequisites.sh
voice-test:
	$(MAKE) -C services/voice test
voice-install:
	sudo bash scripts/install_rover_voice_service.sh --repo-dir "$$(pwd)"
voice-uninstall:
	sudo bash scripts/uninstall_rover_voice_service.sh
voice-audio-test:
	bash scripts/test_voice_audio.sh
```

The audio test checks capture and playback devices, model loading and Piper synthesis. A tone is never played unless `--play-test-tone` is explicitly supplied.

- [ ] **Step 6: Run tests and commit**

Run: `cd services/voice && pytest -q && bash -n ../../scripts/check_voice_prerequisites.sh ../../scripts/install_rover_voice_service.sh ../../scripts/uninstall_rover_voice_service.sh ../../scripts/test_voice_audio.sh`

Expected: PASS.

```bash
git add deploy/jarvis-rover-voice.service scripts/check_voice_prerequisites.sh scripts/install_rover_voice_service.sh scripts/uninstall_rover_voice_service.sh scripts/test_voice_audio.sh Makefile services/voice/tests/test_deployment_config.py
git commit -m "feat: deploy local voice service"
```

---

### Task 8: Integrate the real voice state into the web console

**Files:**
- Modify: `apps/web/src/types/contract.ts:75-159`
- Create: `apps/web/src/lib/voiceClient.ts`
- Modify: `apps/web/src/App.vue:1-126,247-263`
- Create: `apps/web/src/lib/voiceClient.test.ts` if the repository test runner is configured; otherwise add type-level contract tests under the existing web test setup.

**Interfaces:**
- Produces `VoiceStatusState` matching server `VoiceStatus`, with no default transcript or fake confidence.
- Produces `VoiceClient.getStatus(): Promise<VoiceStatusState>`.
- Produces `VoiceClient.sendAssistant(request): Promise<VoiceAssistantResponse>` only for explicitly submitted local transcript test/dev flows; browser must not receive or capture the host microphone in this phase.
- Produces `VoiceClient.startSession()`/`stopSession()` only if the endpoint remains a real status control; these methods must not claim that host capture started unless heartbeat confirms it.

- [ ] **Step 1: Write frontend contract tests**

Test JSON parsing for all real states and null values:

```ts
it('does not invent transcript or confidence for unavailable voice', () => {
  const state = parseVoiceStatus({
    state: 'audio_unavailable',
    enabled: true,
    session_id: null,
    turn_id: null,
    last_error: { code: 'source_unavailable', message: 'USB microphone missing', recoverable: true },
    component_latency_ms: { asr: null, assistant: null, tts: null },
  })

  expect(state.transcript).toBeNull()
  expect(state.confidence).toBeNull()
  expect(state.state).toBe('audio_unavailable')
})
```

Test 401/503/network failure, no local state mutation on failed request, and mapping action response rendering.

- [ ] **Step 2: Run frontend tests/typecheck and verify the new contract is absent**

Run: `cd apps/web && npm run build`

Expected: the new test/contract portions fail until the client and types are added; existing unrelated build failures must be recorded separately rather than hidden.

- [ ] **Step 3: Add schema-checked voice client**

Implement `voiceClient.ts` with `fetch` against the same-origin `/api/v1/voice/status`, no key/token in browser code. Parse state and nested error fields, reject unknown schema versions and preserve null values. Use a bounded polling interval only for voice service status if the telemetry WebSocket does not yet expose `voice_status`; polling must not advance robot pose, task, lidar, camera or any other state.

- [ ] **Step 4: Replace only the voice panel’s mock behavior**

Remove the local `toggleVoice()` mutation of `snapshot.runtime.voice`. Render real `VoiceStatusState` with text for `wake_listening`, `capturing`, `processing_asr`, `processing_assistant`, `speaking`, `audio_unavailable`, `asr_error`, `assistant_unavailable` and `tts_error`. On unavailable/error show the backend reason and last update age; do not show “贾维斯” as a claimed armed state unless status says enabled and wake listening.

The button must request a real session/status endpoint or be disabled with “由宿主机语音服务控制”; it must not pretend to start microphone capture in the browser. Do not add a data URI, static transcript, random confidence or fake microphone state.

- [ ] **Step 5: Run frontend build and commit**

Run: `cd apps/web && npm run build`

Expected: PASS for the web build after adapting the existing types; no new mock voice data is introduced. If the broader existing mock console remains in this separate data-pipeline workstream, document that this task removes only voice-panel mock behavior and does not claim the whole console is real-data complete.

```bash
git add apps/web/src/types/contract.ts apps/web/src/lib/voiceClient.ts apps/web/src/App.vue apps/web/src/lib/voiceClient.test.ts
git commit -m "feat: show real voice service state"
```

---

### Task 9: Update runtime documentation, secret handling, and operational runbook

**Files:**
- Modify: `README.md` in the true-machine deployment section
- Modify: `services/api/README.md`
- Create: `docs/voice-runtime-runbook.md`
- Modify: `.gitignore` if a new local voice environment/model path is not already covered
- Modify: `.env.example` only for names introduced by the implementation

**Interfaces:**
- Produces documented setup for `/opt/jarvis-rover/models`, ALSA stable names, `/etc/jarvis-rover/voice.env`, Python environment, service lifecycle, logs and rollback.
- Documents that AI key was exposed in the conversation and must be rotated before enabling; never repeat the key.
- Documents URLs and local-only gateway boundary without exposing secret values.

- [ ] **Step 1: Write documentation checks**

Add a documentation test/script that fails if tracked files contain an `sk-` token pattern, `Authorization: Bearer` with a non-variable literal, or an actual key value. Check that README includes all of:

```text
openWakeWord
sherpa-onnx
Piper
rover-voice.service
ROVER_AI_BASE_URL
ROVER_AI_MODEL
ROVER_AI_API_KEY
ROVER_VOICE_GATEWAY_TOKEN
ROVER_VOICE_CAPTURE_DEVICE
ROVER_VOICE_PLAYBACK_DEVICE
```

- [ ] **Step 2: Document model installation without auto-download**

Document the required external model assets, source/license/hash recording, exact environment path variables, permissions, and the expected unavailable state when a model is absent. Do not commit model binaries or claim the custom Chinese wakeword model exists until it is present on the real machine.

- [ ] **Step 3: Document secret injection and rotation**

Use `/etc/jarvis-rover/runtime.env` or the existing protected runtime environment for `ROVER_AI_API_KEY`, and `/etc/jarvis-rover/voice.env` mode `0600` for the gateway token/device/model values. Explain that `ROVER_AI_API_KEY` must not be passed to `rover-voice.service`. Include safe commands using variable names only, never a literal secret.

- [ ] **Step 4: Document lifecycle and failure behavior**

Include:

```bash
sudo systemctl enable --now rover-runtime.service
sudo systemctl enable --now rover-voice.service
systemctl status rover-voice.service --no-pager
journalctl -u rover-voice.service -f
make voice-prerequisites
make voice-audio-test
sudo systemctl restart rover-voice.service
sudo bash scripts/uninstall_rover_voice_service.sh
```

State explicitly that start/resume, non-zero `/cmd_vel`, navigation, gimbal and arbitrary ROS commands are never invoked by service startup or voice failure. Add troubleshooting for `arecord -l`, `aplay -l`, missing models, loopback 401/503, GPT endpoint timeout and stale heartbeat.

- [ ] **Step 5: Run documentation/secret checks and commit**

Run: `git diff --check && ! git grep -nE 'sk-[A-Za-z0-9]{20,}|Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._-]{20,}' -- ':!data/evidence'`

Expected: PASS.

```bash
git add README.md services/api/README.md docs/voice-runtime-runbook.md .gitignore .env.example
git commit -m "docs: add local voice runbook"
```

---

### Task 10: Offline verification, integration verification, and authorized real-machine acceptance

**Files:**
- Modify: `scripts/check_runtime_prerequisites.sh` only if it needs to report voice as optional without changing mapping safety checks
- Create: `scripts/verify_voice_integration.sh`
- Create: `services/api/tests/test_voice_integration.py`
- Create: `services/voice/tests/test_end_to_end_fakes.py`
- Create: `docs/evidence/voice-acceptance-template.md` only if evidence templates are tracked; never track raw audio or secrets

**Interfaces:**
- Produces deterministic offline verification with no real GPT request.
- Produces a real-machine checklist that reports camera/voice/model availability honestly.
- Does not change `rover-runtime.service` mapping startup behavior or hardware profile exclusivity.

- [ ] **Step 1: Add offline API-to-fake-voice integration tests**

Exercise:

```text
fake ASR transcript “开始建图”
→ authenticated gateway
→ fake provider structured action
→ awaiting_confirmation
fake ASR transcript “确认”
→ current mapping status recheck
→ fake mapping backend command
→ executed/rejected based on real backend result
```

Assert no `/cmd_vel` call, no arbitrary ROS service name, no task append, no raw audio payload and no secret in logs. Exercise provider unavailable, mapping unavailable, stale voice heartbeat and malformed decision paths.

- [ ] **Step 2: Run all offline tests and build checks**

Run:

```bash
python3 -m venv .venv-voice-plan-check
.venv-voice-plan-check/bin/pip install -e 'services/api[dev]'
.venv-voice-plan-check/bin/pip install -e services/voice
.venv-voice-plan-check/bin/pytest services/api/tests services/voice/tests -q
cd apps/web && npm run build
cd ../..
git diff --check
```

Expected: PASS without Docker, ROS hardware, USB audio or GPT network. Remove the temporary virtual environment after verification; it is ignored and must not be committed.

- [ ] **Step 3: Build and verify runtime without enabling voice hardware**

Run existing runtime build/check commands with `ROVER_AI_ENABLED=false` and empty voice profile. Verify the runtime still starts with mapping `IDLE`, `motion_allowed=false`, no extra `/cmd_vel` publisher and no automatic mapping command. Voice service must remain optional and not be started by `rover-runtime.service`.

- [ ] **Step 4: Run non-destructive real-machine prerequisites**

On the current true machine, after installing model assets and rotating the exposed key:

```bash
make runtime-prerequisites
make voice-prerequisites
arecord -l
aplay -l
systemctl is-active rover-runtime.service
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/v1/voice/status
```

Do not print `.env`, secret files or environment values. If USB devices, models or GPT configuration are missing, record `unavailable` and stop before real API calls.

- [ ] **Step 5: Perform explicitly authorized audio-only checks**

Run `make voice-audio-test` and, only when the user has explicitly authorized playback, `bash scripts/test_voice_audio.sh --play-test-tone`. Confirm 16 kHz mono capture, wakeword model load, sherpa-onnx ASR load and Piper local synthesis. Do not upload audio or call GPT during this step.

- [ ] **Step 6: Perform one authorized end-to-end GPT turn**

After the user rotates/provisions the secret, run one ordinary status question:

```text
你好贾维斯 → “当前建图状态？” → local ASR → loopback gateway → GPT-5.6 → local Piper → USB sound card
```

Record only opaque turn ID, component timings, HTTP status category and resulting voice state. Do not record raw audio, API key, full prompt, full response or complete transcript by default. If GPT fails, report assistant unavailable; do not retry indefinitely.

- [ ] **Step 7: Verify confirmation and safety behavior**

With user authorization, test each mapping action:

```text
开始建图 → confirmation required → 确认 → real backend/state result
暂停建图 → confirmation required → 取消 → no backend call
恢复建图 → expired confirmation → no execution
保存地图 → invalid map name → rejected
停止建图 → state conflict → real rejection
移动/路径/云台 → rejected → no /cmd_vel change
```

Before and after each test, verify `/cmd_vel` publisher ownership and zero output when mapping is idle/locked. Do not claim successful mapping unless the real `/mapping/status` confirms it.

- [ ] **Step 8: Verify isolation and restart behavior**

Restart `rover-voice.service`, stop it, disconnect the network, and restart `rover-runtime.service` independently. Confirm mapping/safety continue, no pending voice action is resumed, local wake/ASR/Piper failure states are visible, and runtime does not require voice. Restore services to their user-approved state without starting mapping or moving the rover.

- [ ] **Step 9: Write honest acceptance report and commit verification scripts**

The report must separate:

```text
offline tests passed
runtime build passed
USB microphone status
USB sound card status
wakeword model status
ASR model status
Piper status
GPT end-to-end status
mapping confirmation status
safety isolation status
unverified items
```

A missing camera is unrelated and remains unavailable; a missing wakeword model or API key is not a successful voice acceptance. Commit only scripts/tests/templates, never private evidence, audio or secrets.

```bash
git add scripts/verify_voice_integration.sh services/api/tests/test_voice_integration.py services/voice/tests/test_end_to_end_fakes.py

git commit -m "test: verify local voice integration"
```

---

## Plan Self-Review

### Spec coverage

- Offline wakeword, VAD, ASR and Piper are covered by Tasks 5–6 and Task 10.
- GPT-5.6 OpenAI-compatible base URL/model/key/timeout/structured output are covered by Tasks 1–3.
- Real mapping context, action allowlist, confirmation TTL and state recheck are covered by Tasks 3–4 and Task 10.
- Loopback/token authentication and secret separation are covered by Tasks 1, 4, 7 and 9.
- Host USB audio deployment and systemd isolation are covered by Tasks 5, 7 and 10.
- Short continuous session, VAD end detection, TTS interruption and bounded queues are covered by Task 6.
- unavailable/error/stale behavior and no mock fallback are covered by Tasks 2–4, 6, 8 and 10.
- Runtime/systemd/safety isolation and no `/cmd_vel` access are covered by Tasks 3, 7 and 10.
- Console voice status is covered by Task 8; the existing broader real map/telemetry migration remains governed by the separate real-data-pipeline spec.
- Model license/hash and no auto-download are covered by Tasks 5, 7 and 9.
- Offline and authorized true-machine acceptance are covered by Task 10.

### Placeholder and consistency checks

- Every step contains concrete commands, interfaces, tests and expected outcomes; none relies on placeholder language or vague implementation instructions.
- The gateway request/response model names are defined in Task 1 and consumed consistently by Tasks 3–6.
- The action names are identical in provider validation, confirmation execution and tests.
- `ROVER_AI_API_KEY` is never placed in the host voice service configuration.
- The plan does not require `rover-runtime.service` to depend on `rover-voice.service`.
- The plan does not claim the custom wakeword model, USB device names or real GPT acceptance exist before machine verification.
- The plan does not authorize an automatic GPT request during installation or offline testing.
