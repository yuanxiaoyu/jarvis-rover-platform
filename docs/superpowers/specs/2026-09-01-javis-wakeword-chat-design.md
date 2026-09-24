# “贾维斯”唤醒与开放对话设计

- 日期：2026-09-01
- 状态：实现完成；Pi 5 本地语音链路已验收，外部模型网络可达性待部署环境确认
- 范围：本地唤醒词配置、开放式 AI 对话、控制台提示和验证

## 目标

用户说“贾维斯”后进入现有的连续短会话；会话内可以进行普通闲聊、知识问答和趣味对话，也可以请求受限的建图操作。助手不因未请求小车动作而拒绝回答。

## 方案

`VoiceConfig` 增加 `wakeword_phrase`（默认 `贾维斯`，环境变量 `ROVER_WAKEWORD_PHRASE`）。唤醒适配器保留 openWakeWord `.onnx` 文件模式；当配置指向 sherpa-onnx KWS 模型目录时，使用本地流式中文关键词检测，并只接受显式配置的“贾维斯”拼音标签。模型文件/目录或依赖缺失时保持 unavailable/error。这样字符串配置不会冒充不存在的唤醒模型。

助手系统提示明确区分两类请求：普通对话返回自然语言；只有开始、暂停、恢复、保存、停止建图可生成结构化 action，仍需本地二次确认。移动、路径、云台、ROS 或 shell 继续禁止。

大模型请求由 FastAPI 统一读取 `ROVER_AI_BASE_URL`、`ROVER_AI_MODEL`、`ROVER_AI_WIRE_API`、
`ROVER_AI_API_KEY` 和 `ROVER_AI_MAX_OUTPUT_TOKENS`。输出 token 配额会按协议映射为 Chat
Completions 的 `max_tokens` 或 Responses 的 `max_output_tokens`；宿主机语音服务只持有独立的
`ROVER_VOICE_GATEWAY_TOKEN`，不接触大模型 key。

前端、README 和运行文档统一使用“贾维斯”，并保留“音频不上云”和模型缺失时的不可用提示。唤醒成功后先播放本地确认短句（默认“我在，请说。”）；确认音播放期间检测到用户讲话时立即打断并进入命令采集。

## 数据流与错误处理

USB 音频、唤醒检测、ASR、TTS 保持宿主机本地运行；网关只接收转写文本和状态。模型输出没有目标短语、模型文件或依赖缺失时，服务不会进入在线监听。助手服务不可用只播报本地错误，不影响小车安全和其他运行时。

TTS 采用显式选择的 Pocket TTS 或中文 sherpa-onnx VITS。两种适配器都使用单个有界 ALSA 播放流：Pocket TTS 使用 `generate_audio_stream`，sherpa-onnx 使用生成回调，在首个 PCM 块可用后立即播放，并在用户讲话时停止。Pi 5 部署默认使用 CPU 和受控采样率；Pocket TTS 的 config、tokenizer、checkpoint 和 voice state 必须是本地文件，运行时禁止远程下载。

## 验证

- 单元测试覆盖短语匹配、阈值和冷却时间。
- API 测试覆盖普通“你好”/趣味对话仍返回 `completed`，以及原有建图确认边界。
- 前端构建和 `git diff --check` 通过。
- 真机验收需额外提供中文 KWS/ASR 与本地 TTS 资产；仓库不提交这些二进制。当前支持的 KWS 目录必须包含 `tokens.txt`、encoder/decoder/joiner、`keywords.txt`（或 `test_wavs/keywords.txt`），并由 sherpa-onnx 在本机加载。ASR 使用流式 Zipformer；TTS 可显式选择 Pocket TTS（需要 checkpoint/voice state）或中文 sherpa VITS（需要 `model.onnx`、`lexicon.txt`、`tokens.txt`），不做静默云端 fallback。
- TTS 假模型测试覆盖首块流式播放、单一 `aplay` 流、采样率转换和播放打断；Pi 5 真机需记录首块延迟、实时系数、CPU/温度和普通话可懂度。

## 2026-09-22 验收记录

- 已通过 `services/api` 34 个测试、`services/voice` 38 个测试、`docker compose config --quiet` 和 `git diff --check`。
- 树莓派 5 的 sherpa-onnx KWS 已加载“贾维斯”，USB 麦克风以 16 kHz 单声道持续采集；语音服务状态为 `wake_listening`。
- 中文 sherpa VITS 通过真实 USB `aplay` 播放“我在，请说。”：首块约 1.40 s，音频约 1.29 s，实时系数约 0.46，测试进程 CPU 约 1.75 s；测试时温度 49.9°C、`throttled=0x0`。
- 真实 `VoiceService` 唤醒确认路径已验证：检测到唤醒后状态进入 `speaking`，确认音播放完成后进入 `capturing`，未触发大模型请求。
- runtime 容器已修复 ROS setup 的 `nounset` 启动问题，并在 8001 端口稳定运行；API 已显式读取 `ROVER_AI_BASE_URL`、`ROVER_AI_MODEL`、`ROVER_AI_WIRE_API` 和 `ROVER_AI_MAX_OUTPUT_TOKENS=512`。
- 当前现场 DNS 无法解析配置的 OpenAI-compatible 地址，因此真实模型请求暂返回 `assistant_unavailable`；本地唤醒确认音和 TTS 不依赖该外部请求。
