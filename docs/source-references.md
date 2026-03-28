# 参考来源说明

本文档记录了本项目在架构设计阶段依赖的外部参考来源。

## Yahboom MicroROS-Pi5

参考页面：

- <https://www.yahboom.com/study/MicroROS-Pi5>
- <https://category.yahboom.net/products/microros-pi5>

从产品页得到的关键结论：

- 小车平台基于 `Raspberry Pi 5`
- 软件栈使用 `ROS2 Humble`
- 控制扩展板基于 `ESP32 micro-ROS`
- 雷达型号为 `MS200`
- 传感器套件包含 `2MP camera` 与 `2DOF gimbal`
- 官方能力覆盖：
  - SLAM 建图与导航
  - RViz 仿真
  - 多机协同
  - App、键盘、手柄控制
  - 跟踪与避障

对架构的影响：

- 保留 `ROS2 + Pi5 + micro-ROS` 的整体假设
- 将雷达建图与导航作为核心能力
- Web 控制台的控制方式尽量与官方控制面保持一致

## Nav2 Keepout Zones

参考页面：

- <https://docs.nav2.org/tutorials/docs/navigation2_with_keepout_filter.html>

关键结论：

- 虚拟墙不应仅停留在浏览器层，而应转换为 keepout mask
- 当希望全局规划和局部规划保持一致时，`global_costmap` 与 `local_costmap` 都应启用 keepout filter
- 地图掩码应当以 `OccupancyGrid` 兼容格式表示

对架构的影响：

- Web 端绘制的虚拟墙会被序列化为 keepout mask 图层
- `rover_safety` 负责在 UI 编辑结果与 Nav2 filter 配置之间做转换

## SLAM Toolbox

参考页面：

- <https://docs.ros.org/en/ros2_packages/humble/api/slam_toolbox/index.html>

关键结论：

- 建图会话不应只支持一次性导出 `.pgm`，还应支持保存与重载
- 序列化的 pose graph 对后续增量建图很有价值
- 定位模式与建图模式应该可以分离运行

对架构的影响：

- 建图流程不仅保存占据栅格，还保存更丰富的会话元数据
- 后续可以扩展为持续建图，而不必每次都全量重建

## sherpa-onnx

参考页面：

- <https://k2-fsa.github.io/sherpa/onnx/index.html>
- <https://k2-fsa.github.io/sherpa/onnx/kws/index.html>
- <https://k2-fsa.github.io/sherpa/onnx/tts/index.html>

关键结论：

- ASR 可在本地离线运行，不依赖互联网
- 开放词表关键词检测支持自定义唤醒词，而不必重新训练整套模型
- 已有中文或中英混合模型可用于关键词唤醒与 TTS
- 文档中包含多个面向树莓派的 TTS 性能说明

对架构的影响：

- `贾维斯` 作为本地唤醒词在技术上可行
- 语音功能应设计为可选适配器，并通过配置开关启用
- 默认部署应先关闭唤醒词与 TTS，待目标硬件实测通过后再打开

## `build-house` 参考项目

本地参考目录：

- `/Users/yuanxiaoyu/Desktop/build-house`

关键结论：

- 可以复用 `IndoorMapScene` 这类 Three.js 场景组织、标签和路径动画思路
- 不应复用其中写死的房屋结构和房间图
- 左侧主视图 + 右侧信息栏的单屏布局值得保留

对架构的影响：

- Web 控制台采用“图层驱动、地图数据驱动”的设计
- 3D 空间由地图几何和语义区域重建，而不是使用固定 demo 房间模型
