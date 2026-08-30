# 真机运行时部署与开机自启动实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 仓库当前策略要求在用户明确要求前不提交或推送；本计划的检查点只运行验证命令并保留工作树，不执行 `git commit`、`git push` 或删除用户数据。

**Goal:** 在当前 Yahboom 真机上部署已构建的 `rover-runtime`，用系统级 systemd 只托管该软件 runtime，开机自动保持运行但始终从 `IDLE`/零速度开始，并把可复现配置和验收命令写入 `README.md`。

**Architecture:** 保留现有官方 Yahboom 容器/Supervisor 作为唯一硬件层；systemd 只执行项目 Compose 的 `rover-runtime` 服务，不启用 `hardware` 或 `micro-ros-agent` profile，不挂载串口，也不自动发送 mapping `start`/`resume`。安装器先安全解析 `.env`、验证 Domain 20、验证 Compose 配置并构建 runtime，再渲染并启用 unit；真机 smoke test 只做健康、ROS graph、状态锁定、零速度和证据采集，不做自动移动。

**Tech Stack:** Bash（严格模式）、Python 3 标准库（无命令执行的 `.env`/unit 渲染辅助）、systemd、Docker Compose、ROS 2 Humble、现有 FastAPI/ROS runtime、pytest。

---

## Scope and file map

这是对已批准的稳定建图运行时计划的独立部署子项目。它不重新实现 Task 1～8 的会话、SLAM 或安全 gate；只修复开机时序所需的 runtime 等待，并增加可测试的部署边界。

### Create

- `scripts/runtime_deployment.py`：纯标准库的 `.env` 安全解析、Domain/profile/生产 bridge 校验和 systemd unit 渲染；不 source `.env`，不启动命令。
- `scripts/check_runtime_prerequisites.sh`：只读部署前检查，确认工具、配置、Docker daemon 和 Compose 默认服务集合可用。
- `scripts/install_rover_runtime_service.sh`：调用前置检查、构建 `rover-runtime`、备份非本项目 unit、安装并启用 systemd 服务；不启动硬件 profile、不调用 mapping API。
- `scripts/uninstall_rover_runtime_service.sh`：停止/禁用并移除项目 unit；不 `docker compose down`，不删除地图、卷、镜像或官方硬件容器。
- `deploy/jarvis-rover-runtime.service`：带 `@REPO_DIR@` 占位符的 systemd 模板。
- `scripts/real_machine_smoke_test.sh`：真机无运动 smoke test，保存 health/status/graph/baseline 输出。
- `scripts/test_runtime_deployment.py`：不需要 ROS、Docker daemon 或 root 的部署契约测试。

### Modify

- `docker/entrypoint.sh`：runtime 模式先等待 mapping service ready，再启动 API；mapping launch 或等待失败时不启动 fake API；保持双进程退出传播和零运动默认。
- `.env.example`：增加 runtime startup timeout 和 evidence directory 示例（保留 Domain 20、required bridge 和关闭语音默认）。
- `README.md`：增加真机部署前置条件、官方硬件启动顺序、systemd 安装/查看/停止/卸载/回滚、无运动 smoke test 和验收证据记录。
- `docs/phase-0-1-runbook.md`：补充本轮自动部署步骤、服务状态和真机出口证据表格；明确安装成功不等于建图验收成功。
- `Makefile`：增加 `runtime-prerequisites`、`runtime-install`、`runtime-uninstall`、`runtime-smoke` 目标，但目标只调用脚本，不隐藏 profile 或运动命令。
- `docs/superpowers/plans/2026-08-28-stable-mapping-runtime.md`：在执行过程中只勾选有命令输出证据的部署/离线步骤，并为 Task 9 记录真机结果或明确的失败原因。

### 不修改/不执行

- 不启动 `yahboom-hardware` 或 `micro-ros-agent` profile；官方硬件仍由现有 `sh ~/ros2_humble.sh`/Supervisor 管理。
- 不自动调用 `/api/v1/mapping/start`、`/resume`、`/stop`，不发布非零 `/cmd_vel`。
- 不执行 `docker compose down --volumes`、`rm -rf data`、删除地图 revision 或覆盖未知的 systemd unit。
- 不把服务健康、ROS graph 通过或代码构建成功描述为 30 分钟真机建图验收。

---

## Task 1: 先锁定部署安全契约与纯 Python 辅助函数

**Files:**
- Create: `scripts/test_runtime_deployment.py`
- Create: `scripts/runtime_deployment.py`

- [ ] **Step 1: Write failing tests for safe env parsing and unit rendering**

测试必须不导入 ROS、不访问 `/etc`、不需要 Docker/root。先写：

```python
from pathlib import Path

import pytest

from runtime_deployment import (
    DeploymentConfigError,
    parse_env_file,
    render_unit,
    validate_runtime_env,
)


def test_parse_env_file_does_not_execute_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ROS_DOMAIN_ID=20\n"
        "ROVER_ROS_BRIDGE_ENABLED=true\n"
        "ROVER_ROS_BRIDGE_REQUIRED=true\n"
        "DANGEROUS=$(touch SHOULD_NOT_EXIST)\n"
        "# ignored=wrong\n",
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values["ROS_DOMAIN_ID"] == "20"
    assert values["DANGEROUS"] == "$(touch SHOULD_NOT_EXIST)"
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_validate_runtime_env_requires_domain_20_and_required_bridge():
    values = {
        "ROS_DOMAIN_ID": "30",
        "ROVER_ROS_BRIDGE_ENABLED": "false",
        "ROVER_ROS_BRIDGE_REQUIRED": "false",
    }

    with pytest.raises(DeploymentConfigError, match="ROS_DOMAIN_ID"):
        validate_runtime_env(values)


def test_validate_runtime_env_rejects_compose_profiles():
    values = {
        "ROS_DOMAIN_ID": "20",
        "ROVER_ROS_BRIDGE_ENABLED": "true",
        "ROVER_ROS_BRIDGE_REQUIRED": "true",
        "COMPOSE_PROFILES": "hardware,micro-ros-agent",
    }

    with pytest.raises(DeploymentConfigError, match="profile"):
        validate_runtime_env(values)


def test_render_unit_replaces_repo_dir_without_shell_evaluation(tmp_path):
    template = "WorkingDirectory=@REPO_DIR@\nExecStart=/usr/bin/docker compose --project-directory @REPO_DIR@ up --no-build rover-runtime\n"

    rendered = render_unit(template, tmp_path)

    assert f"WorkingDirectory={tmp_path}" in rendered
    assert "@REPO_DIR@" not in rendered


def test_render_unit_rejects_whitespace_in_repo_dir():
    with pytest.raises(DeploymentConfigError, match="path"):
        render_unit("@REPO_DIR@", Path("/tmp/rover project"))
```

- [ ] **Step 2: Run the focused test and verify the expected missing-module failure**

Run:

```bash
python3 -m pytest scripts/test_runtime_deployment.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'runtime_deployment'` (or the equivalent missing-symbol error), not a syntax error in the test.

- [ ] **Step 3: Implement the minimal pure helper**

`runtime_deployment.py` 必须只使用标准库，提供以下接口：

```python
from pathlib import Path

class DeploymentConfigError(ValueError):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines without evaluating shell syntax."""


def validate_runtime_env(values: dict[str, str]) -> None:
    """Raise DeploymentConfigError unless production Domain/profile settings are safe."""


def render_unit(template: str, repo_dir: Path) -> str:
    """Replace @REPO_DIR@ after rejecting newline/whitespace path injection."""
```

解析规则固定为：忽略空行和以 `#` 开头的行；key 必须匹配 `[A-Za-z_][A-Za-z0-9_]*`；value 去除一对匹配的单/双引号但不执行 `$()`、反引号或反斜杠命令；重复 key 取最后一项。`validate_runtime_env` 必须要求 `ROS_DOMAIN_ID == "20"`、`ROVER_ROS_BRIDGE_ENABLED` 和 `ROVER_ROS_BRIDGE_REQUIRED` 忽略大小写后为 `true`，并拒绝非空 `COMPOSE_PROFILES`（空白分隔也视为非空）。`render_unit` 必须拒绝绝对路径以外的路径、换行和空白，并且要求模板恰好包含占位符。

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
```

Expected: all helper tests PASS；没有创建 `SHOULD_NOT_EXIST` 文件。

- [ ] **Step 5: Review checkpoint**

运行 `PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q` 和 `git diff --check`；不提交。

---

## Task 2: Add the systemd unit and read-only prerequisite checker

**Files:**
- Create: `deploy/jarvis-rover-runtime.service`
- Create: `scripts/check_runtime_prerequisites.sh`
- Modify: `scripts/test_runtime_deployment.py`

- [ ] **Step 1: Extend the failing contract tests for the unit and checker**

在测试中加入：

```python
UNIT = Path(__file__).parents[1] / "deploy" / "jarvis-rover-runtime.service"
CHECK = Path(__file__).with_name("check_runtime_prerequisites.sh")


def test_unit_manages_only_the_runtime_service():
    text = UNIT.read_text(encoding="utf-8")
    assert "Description=Jarvis Rover runtime" in text
    assert "After=docker.service network-online.target" in text
    assert "Requires=docker.service" in text
    assert "WantedBy=multi-user.target" in text
    assert "up --no-build" in text
    assert "rover-runtime" in text
    assert "--profile" not in text
    assert "yahboom-hardware" not in text
    assert "micro-ros-agent" not in text
    assert "docker compose down" not in text
    assert "/api/v1/mapping/start" not in text
    assert "/api/v1/mapping/resume" not in text


def test_unit_has_restart_and_safe_stop_policy():
    text = UNIT.read_text(encoding="utf-8")
    assert "Restart=on-failure" in text
    assert "TimeoutStopSec=45" in text
    assert "ExecStop=" in text
    assert "stop --timeout 30 rover-runtime" in text
    assert "COMPOSE_PROFILES=" in text


def test_prerequisite_checker_is_strict_and_does_not_start_services():
    text = CHECK.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "docker compose" in text
    assert "config" in text
    assert "ROS_DOMAIN_ID" in text
    assert "enable --now" not in text
    assert "compose up" not in text
    assert "compose start" not in text
```

- [ ] **Step 2: Run the new contract tests and observe the expected file/contract failures**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
```

Expected: FAIL because the unit and checker do not exist yet.

- [ ] **Step 3: Implement the systemd unit template**

`deploy/jarvis-rover-runtime.service` 使用以下结构，`@REPO_DIR@` 由安装器渲染：

```ini
[Unit]
Description=Jarvis Rover runtime (official Yahboom hardware layer)
Wants=network-online.target
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=@REPO_DIR@
Environment=COMPOSE_PROFILES=
Environment=ROS_DOMAIN_ID=20
ExecStart=/usr/bin/docker compose --project-directory @REPO_DIR@ --env-file @REPO_DIR@/.env up --no-build --no-color rover-runtime
ExecStop=/usr/bin/docker compose --project-directory @REPO_DIR@ --env-file @REPO_DIR@/.env stop --timeout 30 rover-runtime
Restart=on-failure
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=45
KillMode=control-group

[Install]
WantedBy=multi-user.target
```

模板必须没有 `--profile`、硬件服务名、串口设备、mapping API 命令或 `down`。`up` 明确只带 `rover-runtime`，所以 Compose 不会选择有 profile 的硬件服务。

- [ ] **Step 4: Implement the read-only prerequisite checker**

`scripts/check_runtime_prerequisites.sh` 的行为固定为：

1. 计算仓库根目录（支持从仓库内任意目录调用），检查 `compose.yaml`、`.env`、`docker/Dockerfile.runtime` 和 `scripts/runtime_deployment.py` 存在；`.env` 不存在时打印 `cp .env.example .env` 并退出 1，不覆盖已有配置。
2. 检查 `python3`、`docker`、`systemctl`、`docker compose` 可执行；运行 `docker info` 确认 daemon 可访问。
3. 运行 `PYTHONPATH="$ROOT/scripts" python3 ...` 调用 `parse_env_file` 和 `validate_runtime_env`，不 source `.env`。
4. 使用 `env -u COMPOSE_PROFILES docker compose --project-directory "$ROOT" --env-file "$ROOT/.env" config --quiet` 校验配置；再用同样的 `env -u` 查询 `config --services`，要求默认服务输出恰为 `rover-runtime`，不把 profile 服务当成默认服务。
5. 只输出通过/失败原因，绝不执行 `compose up`、`start`、`stop`、`down` 或 systemctl 状态改变命令。

脚本必须使用 `set -euo pipefail`，所有路径用双引号，失败时返回非零。

- [ ] **Step 5: Run static contract tests and shell syntax checks**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
bash -n scripts/check_runtime_prerequisites.sh
```

Expected: tests PASS and `bash -n` has no output/exit error。若当前 Docker daemon 尚未可用，只把实际的 prerequisite 命令标为环境阻塞，不把静态契约标为失败。

- [ ] **Step 6: Review checkpoint**

运行 `git diff --check`；确认 unit 的 `ExecStart` 没有 profile/硬件/运动命令，不提交。

---

## Task 3: Implement safe install/uninstall and fix runtime startup ordering

**Files:**
- Create: `scripts/install_rover_runtime_service.sh`
- Create: `scripts/uninstall_rover_runtime_service.sh`
- Modify: `docker/entrypoint.sh`
- Modify: `scripts/test_runtime_deployment.py`
- Modify: `.env.example`

- [ ] **Step 1: Add failing installer/uninstaller and startup-order contract tests**

加入以下静态契约测试：

```python
INSTALL = Path(__file__).with_name("install_rover_runtime_service.sh")
UNINSTALL = Path(__file__).with_name("uninstall_rover_runtime_service.sh")
ENTRYPOINT = Path(__file__).parents[1] / "docker" / "entrypoint.sh"


def test_installer_checks_before_installing_and_never_enables_profiles():
    text = INSTALL.read_text(encoding="utf-8")
    assert "check_runtime_prerequisites.sh" in text
    assert "docker compose" in text and "build rover-runtime" in text
    assert "daemon-reload" in text
    assert "enable --now jarvis-rover-runtime.service" in text
    assert "hardware" not in text.lower() or "profile" in text.lower()
    assert "micro-ros-agent" not in text
    assert "mapping/start" not in text
    assert "mapping/resume" not in text


def test_uninstaller_does_not_delete_data_or_use_compose_down():
    text = UNINSTALL.read_text(encoding="utf-8")
    assert "disable --now jarvis-rover-runtime.service" in text
    assert "daemon-reload" in text
    assert "docker compose down" not in text
    assert "rm -rf" not in text
    assert "/workspace/data" not in text


def test_runtime_waits_for_mapping_service_before_starting_api():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert "ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS" in text
    assert "mapping service" in text.lower()
    assert "ros2 service list" in text
    assert text.index("mapping_pid=") < text.index("uvicorn")
    assert "mapping launch failed before API startup" in text
```

- [ ] **Step 2: Run the focused tests and observe the expected missing-file/contract failure**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
```

Expected: FAIL because the installer, uninstaller and startup wait contract are not present.

- [ ] **Step 3: Implement the installer with explicit backup and no data deletion**

`scripts/install_rover_runtime_service.sh` 必须：

1. 解析自身所在仓库根目录；支持 `--repo-dir PATH`，默认当前 checkout 的父目录；拒绝不存在或含换行/空白的路径。
2. 要求 root（未 root 时打印 `sudo scripts/install_rover_runtime_service.sh` 并退出），但在提权前完成路径解析。
3. 调用 `check_runtime_prerequisites.sh`；通过后运行：

   ```bash
   env -u COMPOSE_PROFILES docker compose \
     --project-directory "$ROOT" --env-file "$ROOT/.env" \
     config --quiet
   env -u COMPOSE_PROFILES docker compose \
     --project-directory "$ROOT" --env-file "$ROOT/.env" \
     build rover-runtime
   ```

4. 用 `runtime_deployment.render_unit` 把模板渲染到临时文件，再安装为 `/etc/systemd/system/jarvis-rover-runtime.service`。若目标已有文件且不包含本项目 managed marker，则先复制为 `/etc/systemd/system/jarvis-rover-runtime.service.bak.<UTC timestamp>`，保留原文件；若备份失败则停止，不覆盖。
5. 执行 `systemctl daemon-reload`、`systemctl enable --now jarvis-rover-runtime.service`，等待最多 60 秒确认 unit active；失败时打印 `systemctl status` 和最近 journald 行，但不删除地图或回滚未知 unit。
6. 只启动 `rover-runtime`。脚本文本和命令行禁止 `--profile hardware`、`--profile micro-ros-agent`、硬件容器、micro-ROS agent、`/start`、`/resume` 和非零速度。
7. 打印下一步只读验证命令：`systemctl status`、`journalctl`、`scripts/real_machine_smoke_test.sh`；不要在安装脚本内调用 mapping API。

安装动作属于已批准的本机 systemd 外部变更；不要在脚本中执行 `docker compose down` 或删除任何 volume。

- [ ] **Step 4: Implement the uninstaller as a narrow reversible operation**

`scripts/uninstall_rover_runtime_service.sh` 必须要求 root，且只执行：

```bash
systemctl disable --now jarvis-rover-runtime.service || true
rm -f /etc/systemd/system/jarvis-rover-runtime.service
systemctl daemon-reload
systemctl reset-failed jarvis-rover-runtime.service || true
```

删除 unit 前若文件不是本项目 managed marker，必须拒绝删除并打印路径。脚本不停止官方硬件容器，不调用 `docker compose down`，不删 `/workspace/data`、仓库 `data/`、镜像或卷。

- [ ] **Step 5: Fix runtime startup ordering without weakening production bridge policy**

在 `docker/entrypoint.sh` 的 `runtime)` 中：

1. 计算 `mapping_pid` 后，轮询 `ros2 service list` 直到 `/mapping/command` 出现；超时使用 `${ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS:-60}`。
2. 轮询期间若 `mapping_pid` 已退出，打印 `mapping launch failed before API startup`，清理并返回非零；超时同样停止 mapping 并返回非零。
3. 只有 mapping service ready 后才启动 `uvicorn`。因此 `ROVER_ROS_BRIDGE_REQUIRED=true` 仍然 fail-fast，但不会在 ROS launch 正常启动的竞态窗口内误判 bridge 不可用。
4. 保留现有 TERM/INT trap、mapping/API 任一进程退出即停止另一进程、非零退出码传播；等待循环不能 `exec bash` 留住已退出的子进程。
5. `mapping)`、`bringup)`、`probe)` 和 `shell)` 行为不变。

`.env.example` 增加：

```dotenv
ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS=60
ROVER_RUNTIME_EVIDENCE_DIR=/workspace/data/evidence
```

- [ ] **Step 6: Run focused tests and shell checks**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
bash -n scripts/install_rover_runtime_service.sh
bash -n scripts/uninstall_rover_runtime_service.sh
bash -n docker/entrypoint.sh
```

Expected: all contract tests PASS and all shell scripts parse successfully。

- [ ] **Step 7: Review checkpoint**

运行 `git diff --check`，人工检查 installer/uninstaller 的每一条外部命令；确认 uninstall 不会删除地图，installer 不会启用硬件 profile，不提交。

---

## Task 4: Add the no-motion real-machine smoke test and evidence capture

**Files:**
- Create: `scripts/real_machine_smoke_test.sh`
- Modify: `scripts/test_runtime_deployment.py`
- Modify: `Makefile`

- [ ] **Step 1: Write failing smoke-test contract tests**

加入：

```python
SMOKE = Path(__file__).with_name("real_machine_smoke_test.sh")
MAKEFILE = Path(__file__).parents[1] / "Makefile"


def test_smoke_test_checks_locked_initial_state_and_never_starts_mapping():
    text = SMOKE.read_text(encoding="utf-8")
    assert "curl -fsS" in text
    assert "/api/v1/mapping" in text
    assert "motion_allowed" in text
    assert '"idle"' in text
    assert "mapping/start" not in text
    assert "mapping/resume" not in text
    assert "cmd_vel" in text
    assert "measure_ros_baseline.sh" in text
    assert "verify_ros_graph.sh" in text


def test_makefile_exposes_explicit_runtime_targets():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "runtime-prerequisites:" in text
    assert "runtime-install:" in text
    assert "runtime-uninstall:" in text
    assert "runtime-smoke:" in text
```

- [ ] **Step 2: Run tests and observe the expected missing smoke script/targets failure**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
```

Expected: FAIL because the smoke script and Make targets do not yet exist.

- [ ] **Step 3: Implement the smoke test with explicit zero-motion assertions**

`scripts/real_machine_smoke_test.sh` 必须在项目 runtime 容器内执行且使用严格模式：

1. 解析 `ROVER_RUNTIME_CONTAINER`（默认 `jarvis-rover-runtime`）和 evidence 目录（默认仓库 `data/evidence/<UTC timestamp>`）；只创建项目 `data` 子目录。
2. 确认 `docker inspect` 显示容器正在运行，调用 `curl -fsS http://127.0.0.1:8000/health`，保存 `health.json`。
3. 调用 `GET /api/v1/mapping`，保存 `mapping-status.json`，用 Python 标准库断言首次状态 `state == "idle"` 且 `motion_allowed is False`；若不满足，退出 1，不调用任何 mapping mutation endpoint。
4. 在容器内运行并保存：

   ```bash
   bash /workspace/scripts/verify_ros_graph.sh
   bash /workspace/scripts/measure_ros_baseline.sh
   ros2 node list
   ros2 topic echo /mapping/status --once
   ros2 topic echo /cmd_vel --once
   ros2 service list | grep -E '/mapping/command|/slam_toolbox/'
   ```

   `measure_ros_baseline.sh` 生成的 JSON 路径复制到 evidence 目录；graph check 失败必须让 smoke test 失败。
5. 对一次 `/cmd_vel` 样本检查 linear.x/y/z 和 angular.x/y/z 均为零；如果 ROS CLI 输出格式在当前 Humble 镜像不同，保存原始输出并以明确失败结束，不用 `|| true` 吞掉运动检查。
6. 最后输出 evidence 目录、unit 状态和“未发送 start/resume/非零运动命令”的声明。脚本本身不调用 systemctl stop、mapping start/resume 或硬件 profile。

如果首次状态是 `error_recoverable`，这是 runtime/ROS 配置失败证据，smoke test 必须失败而不是降级 fake backend。

- [ ] **Step 4: Add Make targets**

在 `Makefile` 增加：

```make
runtime-prerequisites:
	bash scripts/check_runtime_prerequisites.sh

runtime-install:
	bash scripts/install_rover_runtime_service.sh

runtime-uninstall:
	bash scripts/uninstall_rover_runtime_service.sh

runtime-smoke:
	bash scripts/real_machine_smoke_test.sh
```

更新 `.PHONY`，不把任何 profile、API mutation 或 `docker compose down` 隐藏到 Make target 中。

- [ ] **Step 5: Run static tests and shell checks**

Run:

```bash
PYTHONPATH=scripts python3 -m pytest scripts/test_runtime_deployment.py -q
bash -n scripts/real_machine_smoke_test.sh
make -n runtime-prerequisites runtime-install runtime-uninstall runtime-smoke
```

Expected: tests PASS，shell syntax PASS，`make -n` 只显示对应脚本调用，不执行真机动作。

- [ ] **Step 6: Review checkpoint**

确认 smoke test 没有 `curl -X POST`、`mapping/start`、`mapping/resume` 或非零速度输入；执行 `git diff --check`，不提交。

---

## Task 5: Record installation and operating procedure in README/runbook

**Files:**
- Modify: `README.md`
- Modify: `docs/phase-0-1-runbook.md`
- Modify: `.env.example`

- [ ] **Step 1: Add the approved official-hardware + runtime procedure verbatim**

在 `README.md` 增加“真机部署与 systemd 开机自启动”章节，至少包含以下可复制流程：

```bash
cd /home/jarvis-rover-platform

# 只在 .env 不存在时创建；已有 .env 不覆盖
if [ ! -f .env ]; then cp .env.example .env; fi
# 编辑 .env，确认 ROS_DOMAIN_ID=20、ROVER_ROS_BRIDGE_ENABLED=true、
# ROVER_ROS_BRIDGE_REQUIRED=true，且没有 COMPOSE_PROFILES=hardware,micro-ros-agent

# 先由官方脚本/Supervisor 启动唯一 Yahboom 硬件层
sh ~/ros2_humble.sh
# 官方容器内只运行底盘、雷达、IMU、odom 和已重映射到 /cmd_vel_teleop 的手柄。
# 不要在第二个容器中启动官方 EKF、Cartographer 或 GMapping。

make runtime-prerequisites
sudo scripts/install_rover_runtime_service.sh
systemctl status jarvis-rover-runtime.service
journalctl -u jarvis-rover-runtime.service -f

# 只读、无运动 smoke test
make runtime-smoke
```

文档必须明确：本拓扑不执行 `docker compose --profile hardware`、不启动 `micro-ros-agent`，不再运行第二份 `sh ~/ros2_humble.sh`；如果官方手柄仍发布 `/cmd_vel` 而非 `/cmd_vel_teleop`，先按 runbook 完成 vendor remap，否则 graph check 必须失败。

- [ ] **Step 2: Document service lifecycle, rollback and data retention**

README 必须记录：

```bash
systemctl is-enabled jarvis-rover-runtime.service
systemctl is-active jarvis-rover-runtime.service
journalctl -u jarvis-rover-runtime.service --since boot
sudo systemctl restart jarvis-rover-runtime.service
sudo systemctl stop jarvis-rover-runtime.service
sudo systemctl disable jarvis-rover-runtime.service
sudo scripts/uninstall_rover_runtime_service.sh
```

并说明：

- `stop`/`disable` 只影响项目 runtime，不停止官方硬件容器；
- uninstall 不删除 `data/`、`/workspace/data/maps`、容器镜像、volume 或 backup unit；
- 安装器发现未知的同名 unit 会先备份并拒绝静默覆盖；恢复备份前必须人工检查；
- unit 启动后 mapping 初始为 `idle`、`motion_allowed=false`，不会自动恢复上一次会话；
- runtime/API/SLAM 故障时 gate 继续零速，服务健康不等于阶段 1 真机验收。

- [ ] **Step 3: Document evidence and acceptance distinctions**

README/runbook 增加证据表：

| 层级 | 命令/证据 | 含义 |
|---|---|---|
| 配置 | `make runtime-prerequisites`、`docker compose config` | Domain/profile/Compose 配置可部署 |
| 服务 | `systemctl is-active`、health JSON | runtime 进程和 API 存活 |
| ROS 图 | `verify_ros_graph.sh` 输出 | 唯一 EKF/SLAM/TF/control graph 满足契约 |
| 初始安全 | `mapping-status.json`、`/cmd_vel` 零速样本 | 开机没有自动运动 |
| 资源基线 | baseline JSON | 记录实际频率、QoS、CPU、内存、温度；若 runtime 已启 SLAM，不能称 no-SLAM baseline |
| 阶段 1 | 30 分钟、5 次 pause/resume、save/load、搬运恢复、故障注入日志 | 真机建图出口验收，不能由构建或 smoke test 代替 |

增加证据目录约定 `data/evidence/<UTC timestamp>/`，并说明敏感日志不要上传公共仓库。

- [ ] **Step 4: Update environment and runbook safety notes**

`.env.example` 添加：

```dotenv
ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS=60
ROVER_RUNTIME_EVIDENCE_DIR=/workspace/data/evidence
```

`docs/phase-0-1-runbook.md` 补充本轮“部署后但未运动”的检查清单，并保留 Task 9 的真机人工运动项目为未完成，直到有实际日志/JSON/时间/硬件 digest。

- [ ] **Step 5: Run documentation consistency checks**

Run:

```bash
grep -RInE 'ROS_DOMAIN_ID|COMPOSE_PROFILES|jarvis-rover-runtime|runtime-smoke|mapping/start|mapping/resume|hardware|micro-ros-agent' README.md docs/phase-0-1-runbook.md .env.example docker/entrypoint.sh deploy scripts
```

Expected: 所有生产开机示例为 Domain 20；systemd 只托管 `rover-runtime`；README 明确 `mapping/start`/`resume` 是人工后续命令而非安装动作；没有文档声称 smoke test 完成真机性能验收。

- [ ] **Step 6: Review checkpoint**

运行 `git diff --check`；检查 README 没有 TODO/TBD、未定义命令或把 fake backend 描述为真机；不提交。

---

## Task 6: Execute offline validation, deploy to this real machine, and collect safe evidence

**Files:**
- Modify: `docs/phase-0-1-runbook.md`（只填写实际命令输出的日期、路径和结果）
- Modify: `docs/superpowers/plans/2026-08-28-stable-mapping-runtime.md`（只勾选有证据的步骤）

- [ ] **Step 1: Create an isolated venv and run offline tests**

在当前 worktree 创建 `.venv`（已被 `.gitignore` 忽略），安装 API dev 依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e 'services/api[dev]'
PYTHONPATH=scripts .venv/bin/python -m pytest scripts/test_runtime_deployment.py -q
PYTHONPATH=scripts .venv/bin/python -m pytest services/api/tests -q
```

若 ROS 消息导入导致 gate 测试只能在 ROS 容器运行，明确记录宿主环境缺失，不安装系统包、不伪造通过。

- [ ] **Step 2: Run static/container preflight before changing boot state**

Run:

```bash
bash -n scripts/*.sh docker/entrypoint.sh
PYTHONPATH=scripts .venv/bin/python -m compileall -q scripts services/api/app
make -n runtime-prerequisites runtime-install runtime-smoke
bash scripts/check_runtime_prerequisites.sh
```

Expected: 前三项无错误；前置检查报告 Docker/Compose、`.env`、Domain 20、required bridge 和默认服务集合。任何失败先修复或记录原因，不执行 systemd enable。

- [ ] **Step 3: Confirm exactly one official hardware topology before install**

只读执行：

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
ros2 node list
ros2 topic list
```

确认已存在的官方硬件层发布 `/scan`、`/odom_raw`、`/imu`，手柄输出为 `/cmd_vel_teleop`；确认没有第二个 Yahboom 容器、micro-ROS agent、EKF、Cartographer、GMapping 或项目 runtime。若发现重复硬件/agent，停止部署并记录失败，不自动停止外部容器。

- [ ] **Step 4: Build and enable only rover-runtime**

在前置检查和用户已批准的 system-level 变更范围内运行：

```bash
sudo scripts/install_rover_runtime_service.sh
systemctl is-enabled jarvis-rover-runtime.service
systemctl is-active jarvis-rover-runtime.service
```

安装器预期构建 `rover-runtime`，备份未知 unit（如有），执行 `daemon-reload` 和 `enable --now`，不启动硬件 profile。若服务启动失败，保存：

```bash
systemctl status jarvis-rover-runtime.service --no-pager
journalctl -u jarvis-rover-runtime.service -n 200 --no-pager
```

不得为了“通过”而把 `ROVER_ROS_BRIDGE_REQUIRED` 改成 false、启用 fake backend、关闭安全 gate 或绕过 graph check。

- [ ] **Step 5: Run no-motion smoke and save evidence**

Run:

```bash
scripts/real_machine_smoke_test.sh
```

预期证据包括 health、mapping status `idle/false`、ROS graph、节点/服务列表、零速样本和 runtime 资源 JSON。任何 graph、状态或零速断言失败都标为失败；不要调用 start/resume 修复 smoke test。

- [ ] **Step 6: Perform only explicitly supervised manual motion acceptance**

本步骤不由安装器自动完成，且只能在抬轮/安全场地和人工确认后执行。按 `docs/phase-0-1-runbook.md` 手动记录：

1. API `/start` 后低速人工遥控；
2. 原地 pause/resume 至少 5 次，确认 pause 先零速；
3. save/stop/restart/load known-free pose/resume；
4. occupied/unknown/out-of-bounds pose 拒绝；
5. 30 分钟性能指标；
6. SLAM/API/写盘/runtime 重启故障注入。

如果用户没有另行要求执行运动测试，本轮只完成 Step 5，并将这些项目保持未验收。

- [ ] **Step 7: Update evidence records and plan checkboxes conservatively**

只把有实际输出路径和结果的离线/部署步骤勾选。将真实日期（2026-08-30 或执行当天）、unit 状态、镜像 digest、evidence 目录、失败项和环境前置条件写入 runbook；Task 9 的人工运动项目没有证据时保持 `- [ ]`。

- [ ] **Step 8: Final verification before reporting**

Run:

```bash
git diff --check
PYTHONPATH=scripts .venv/bin/python -m pytest scripts/test_runtime_deployment.py services/api/tests -q
systemctl is-active jarvis-rover-runtime.service
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/v1/mapping
```

如果 ROS/container/pytest/Docker 任一环境条件不满足，报告精确的失败输出；不得用“代码已写入”替代真机证据。确认服务仍为 enabled/active、初始 mapping 状态锁定且没有自动运动后，才报告部署结果。

- [ ] **Step 9: Review checkpoint**

最终检查 diff 只覆盖部署、自启动、README/runbook、启动时序和验证证据；没有 profile 重复启动、自动建图、删除数据或阶段 2～4 功能；不提交、不推送。

---

## Execution dependencies

```text
Task 1 pure helper tests
        ↓
Task 2 unit + read-only preflight
        ↓
Task 3 installer/uninstaller + runtime startup ordering
        ↓
Task 4 no-motion smoke/evidence commands
        ↓
Task 5 README/runbook/Make documentation
        ↓
Task 6 offline validation → topology check → runtime install → safe smoke
```

Task 1～5 可以在没有真机动作的环境完成；Task 6 Step 3～5 才访问当前真机的 Docker/ROS 图。Task 6 Step 6 的非零运动和故障注入只由人工按 runbook 执行，不会由部署脚本代替。

## Plan self-check

- 已覆盖批准设计中的 systemd system-level unit、官方硬件 + runtime 互斥拓扑、安装/卸载、回滚、README 配置记录和真机测试证据。
- 已明确 installer 不启动 hardware/micro-ros-agent、不挂载串口、不调用 mapping start/resume；unit 只管理 `rover-runtime`。
- 已补充 mapping service readiness，避免 required ROS bridge 在启动竞态中误失败，但没有把 production bridge 改成 fake fallback。
- 已为新增纯 Python helper、unit、shell installer/uninstaller、entrypoint startup wait、smoke test 和 Make targets 安排先失败测试或静态契约测试。
- 未使用 TODO/TBD/稍后补充作为实现步骤；Task 9 真机性能/运动出口没有被离线测试冒充完成。
