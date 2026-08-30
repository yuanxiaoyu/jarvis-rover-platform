# 树莓派运行配置建议

## 目标

在 Raspberry Pi 5 + ROS 2 Humble 上保持小车主链路响应流畅，同时支持：

- 异步 SLAM 建图与会话恢复；
- 后续持续导航；
- 地图与遥测实时推送；
- 可选浏览器摄像头预览；
- 可选本地语音能力。

真机当前使用 `ROS_DOMAIN_ID=20`；项目和所有容器必须保持一致。

## 阶段 0～1 默认运行档位

- Yahboom 硬件驱动：开启且只运行一份；
- `robot_localization` EKF：开启且只运行一份；
- `slam_toolbox online_async`：开启且只运行一份；
- 本地安全 watchdog/速度门控：开启；
- Web API 与有界状态推送：开启；
- RViz：关闭；
- rosbridge：关闭，只有调试需要时单独启用；
- 摄像头推送：关闭或使用中等帧率 MJPEG；
- 本地唤醒词：关闭；
- 本地 ASR：关闭；
- 本地 TTS：关闭。

建图和控制是主任务能力，语音、3D 展示和媒体流不能争抢控制环路资源。

## 进程与通信隔离

- Yahboom 容器只运行硬件驱动、雷达、IMU、里程计和输入设备；
- 项目 runtime 运行滤波、EKF、TF、SLAM、mapping session manager 和 safety gate；
- SLAM、保存、压缩和 API 不使用无限队列；
- 保存和地图快照写入独立 worker，ROS 回调不等待 SD 卡；
- Web 客户端落后时丢弃旧地图/雷达快照；
- 语音推理运行在独立进程或线程；不能阻塞安全话题 executor；
- 摄像头拥塞时降低帧率或丢帧，不能降低控制频率；
- 同一时刻不得存在第二个 micro-ROS agent、EKF、`map -> odom` publisher 或最终 `/cmd_vel` publisher。

## SLAM 初始策略

`slam_toolbox` 使用 `online_async`，初始参数集中在 `rover_mapping/params/slam_toolbox_online_async.yaml`：

- `use_sim_time=false`；
- `map_update_interval=1.0`；
- `transform_publish_period=0.05`；
- `minimum_time_interval=0.20`；
- `minimum_travel_distance=0.10`、`minimum_travel_heading=0.10`；
- `throttle_scans=1`；
- 雷达有效范围初始限制为 6 m；
- 扫描和 Web 队列保持有界；
- 回环关闭策略只在真机基准显示必要时再调整。

这些是 Pi 5 的可测基线，不是对每个 MS200 固件版本的最终标定。Cartographer 只能在项目 SLAM 停止后单独作为对照。

## 性能验收目标

阶段 0 先运行 no-SLAM baseline，再对比启用 SLAM/API：

- 连续运行 30 分钟无 OOM、swap 抖动或明显热降频；
- 最终控制指令 p99 间隔不超过 250 ms；
- 地图更新延迟 p95 不超过 2 s；
- `/scan`、`/odom_raw`、`/imu` 频率相对 no-SLAM 基线下降不超过 5%；
- 无持续 TF lookup、message-filter 或时间戳错误。

当目标不能满足时，按以下顺序降级：

1. 关闭语音；
2. 关闭摄像头或降低媒体帧率；
3. 降低地图/雷达 Web 推送频率；
4. 调整 SLAM 扫描抽样和回环参数；
5. 最后才评估传感器发布策略。

不能通过关闭安全层或放宽控制 watchdog 达标。

## 语音能力分级

### 第 0 级：仅浏览器语音

- 麦克风采集在浏览器侧完成；
- 后端接收转写文本或音频分片；
- 机器人本地不运行唤醒词。

### 第 1 级：按键说话 + 本地 ASR

- 不启用常驻唤醒词；
- 只有明确开始语音会话时运行 ASR；
- 通过独立 worker 限制 CPU 和内存。

### 第 2 级：唤醒词 + ASR + TTS

- 本地唤醒词为 `贾维斯`；
- 唤醒后进入流式 ASR；
- 按需通过 TTS 播报确认或结果；
- 只有真机温度、延迟、建图和控制指标全部通过后启用。

推荐统一适配层为 `sherpa-onnx`；默认关闭以下能力：

```dotenv
ROVER_ENABLE_WAKE_WORD=false
ROVER_ENABLE_ASR=false
ROVER_ENABLE_TTS=false
```

## 部署环境变量

`.env.example` 提供以下默认值：

```dotenv
ROS_DOMAIN_ID=20
ROVER_ROS_BRIDGE_ENABLED=true
ROVER_ROS_BRIDGE_REQUIRED=true
ROVER_ROS_SERVICE_TIMEOUT_SECONDS=10
ROVER_MAPPING_SESSION_DIR=/workspace/data/maps
ROVER_BASELINE_DURATION_SECONDS=10
ROVER_CAMERA_STREAM_MODE=mjpeg
ROVER_TELEMETRY_HZ=2
ROVER_LIDAR_DOWNSAMPLE=1
```

语音开关保持关闭，硬件串口由唯一的硬件拓扑负责：

```dotenv
MICROROS_SERIAL_DEVICE=/dev/myserial
MICROROS_SERIAL_BAUD=115200
```

## 故障回退顺序

发生 SLAM、API、写盘或 ROS graph 故障时：

1. safety gate 输出零速度；
2. 保留上一份完整 `current.json` 和 revision；
3. mapping 状态变为 `error_recoverable`；
4. 通过诊断信息报告失败原因；
5. 人工确认硬件/TF/文件状态后，才允许显式恢复；
6. 不自动恢复行驶。
