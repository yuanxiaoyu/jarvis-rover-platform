<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { createInitialSnapshot } from '@/data/realSnapshot'
import { RoverScene } from '@/lib/roverScene'
import { fetchVoiceStatus } from '@/lib/voiceClient'
import type { RoverSnapshot } from '@/types/contract'

const snapshot = ref<RoverSnapshot>(createInitialSnapshot())
const aiCommand = ref('')
const sceneHost = ref<HTMLDivElement | null>(null)
const ttsText = ref('')
const ttsEnabled = ref(true)
const ttsMessage = ref('')

let scene: RoverScene | null = null
let voiceTimer: number | null = null
const voiceStatus = ref<Awaited<ReturnType<typeof fetchVoiceStatus>> | null>(null)

const selectedZone = computed(
  () => snapshot.value.world.zones.find((zone) => zone.id === snapshot.value.runtime.selectedZoneId) ?? null,
)
const activeTask = computed(
  () => snapshot.value.runtime.tasks.find((task) => task.status === 'running') ?? snapshot.value.runtime.tasks[0],
)
const enabledWalls = computed(
  () => snapshot.value.world.virtualWalls.filter((wall) => wall.enabled).length,
)
const selectableZones = computed(() => snapshot.value.world.zones.filter((zone) => zone.selectable))

function updateStatusLine(message: string): void {
  snapshot.value.runtime.mission.statusLine = message
}

function selectZone(zoneId: string): void {
  snapshot.value.runtime.selectedZoneId = zoneId
  const zone = snapshot.value.world.zones.find((item) => item.id === zoneId)
  updateStatusLine(zone ? `已锁定目标区域：${zone.name}` : '已更新目标区域')
  scene?.setRuntime(snapshot.value.runtime)
}

function toggleWall(wallId: string): void {
  snapshot.value.world.virtualWalls = snapshot.value.world.virtualWalls.map((wall) =>
    wall.id === wallId ? { ...wall, enabled: !wall.enabled } : wall,
  )
  updateStatusLine('虚拟墙配置已更新')
  scene?.setWorld(snapshot.value.world)
  scene?.setRuntime(snapshot.value.runtime)
}

async function submitAiCommand(): Promise<void> {
  const prompt = aiCommand.value.trim()
  if (!prompt) {
    return
  }
  updateStatusLine('AI 指令需要通过本地语音网关提交；当前浏览器不会伪造任务状态')
}

async function refreshVoiceStatus(): Promise<void> {
  try { voiceStatus.value = await fetchVoiceStatus() } catch { voiceStatus.value = null }
}

async function speakText(): Promise<void> {
  const text = ttsText.value.trim()
  if (!text || !ttsEnabled.value) return
  try {
    const assistantResponse = await fetch('/api/v1/voice/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema_version: 1, session_id: `web-${Date.now()}`, turn_id: `turn-${Date.now()}`, transcript: text, language: 'zh-CN', confidence: 1, source: 'local-sherpa-onnx' }),
    })
    if (!assistantResponse.ok) throw new Error(`assistant ${assistantResponse.status}`)
    const assistant = await assistantResponse.json() as {
      state?: string
      reply_text?: string
      error?: { message?: string }
    }
    if (assistant.state !== 'completed' || !assistant.reply_text || assistant.error) {
      throw new Error(assistant.error?.message ?? 'assistant unavailable')
    }
    const response = await fetch('/api/v1/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: assistant.reply_text }) })
    if (!response.ok) throw new Error(`tts ${response.status}`)
    ttsMessage.value = `大模型回复：${assistant.reply_text}`
    ttsText.value = ''
  } catch {
    ttsMessage.value = '大模型或语音服务不可用，请检查 runtime 配置'
  }
}

async function sendMission(action: 'start' | 'pause' | 'return' | 'clear'): Promise<void> {
  const endpoint = action === 'start' ? '/api/v1/mapping/start' : action === 'pause' ? '/api/v1/mapping/pause' : action === 'clear' ? '/api/v1/mapping/stop' : ''
  if (!endpoint) { updateStatusLine('返航能力未接入真实 runtime'); return }
  try {
    const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: action === 'start' ? JSON.stringify({ session_id: `web-${Date.now()}` }) : undefined })
    updateStatusLine(response.ok ? 'runtime 已接收请求，等待真实状态更新' : `runtime 请求失败（${response.status}）`)
  } catch { updateStatusLine('runtime 不可用') }
}

onMounted(() => {
  if (!sceneHost.value) {
    return
  }

  scene = new RoverScene(sceneHost.value, {
    onZoneSelect: (zoneId) => selectZone(zoneId),
  })
  scene.setWorld(snapshot.value.world)
  scene.setRuntime(snapshot.value.runtime)
  refreshVoiceStatus()
  voiceTimer = window.setInterval(refreshVoiceStatus, 5000)

})

onBeforeUnmount(() => {
  if (voiceTimer !== null) window.clearInterval(voiceTimer)
  scene?.destroy()
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">JARVIS ROVER / ROS2 HUMBLE / MICRO-ROS PI5</p>
        <h1>贾维斯小车一屏控制台</h1>
      </div>
      <div class="topbar__chips">
        <span class="chip chip--accent">地图：{{ snapshot.world.mapName }}</span>
        <span class="chip">模式：{{ snapshot.runtime.mission.mode }}</span>
        <span class="chip">虚拟墙：{{ enabledWalls }}/{{ snapshot.world.virtualWalls.length }}</span>
      </div>
    </header>

    <main class="dashboard">
      <section class="stage">
        <div class="stage__header">
          <div>
            <p class="eyebrow">Map + 3D Space Reconstruction</p>
            <h2>{{ selectedZone?.name ?? '等待选区' }}</h2>
            <p class="stage__description">{{ snapshot.runtime.mission.statusLine }}</p>
          </div>

          <div class="status-grid">
            <article>
              <span>定位置信度</span>
              <strong>{{ Math.round(snapshot.runtime.telemetry.localizationConfidence * 100) }}%</strong>
            </article>
            <article>
              <span>电量</span>
              <strong>{{ Math.round(snapshot.runtime.telemetry.batteryPercent) }}%</strong>
            </article>
            <article>
              <span>实时时延</span>
              <strong>{{ Math.round(snapshot.runtime.telemetry.networkRttMs) }} ms</strong>
            </article>
          </div>
        </div>

        <div class="stage__viewer">
          <div ref="sceneHost" class="scene-host" />

          <div class="overlay overlay--top">
            <span class="overlay-pill">MS200 TOF 建图</span>
            <span class="overlay-pill">2D 栅格 + 3D 重建</span>
            <span class="overlay-pill">实时雷达点云叠加</span>
          </div>

          <div class="overlay overlay--left">
            <div class="mini-card">
              <span>当前任务</span>
              <strong>{{ activeTask?.title ?? '暂无任务' }}</strong>
              <small>进度 {{ activeTask?.progressPct ?? 0 }}%</small>
            </div>
            <div class="mini-card">
              <span>路径状态</span>
              <strong>{{ snapshot.runtime.path.status }}</strong>
              <small>{{ snapshot.runtime.path.waypoints.length }} 个路径点</small>
            </div>
          </div>

          <div class="overlay overlay--bottom">
            <article class="media-card">
              <div class="media-card__head">
                <span>{{ snapshot.runtime.camera.title }}</span>
                <strong>{{ snapshot.runtime.camera.connected ? '在线' : '离线' }}</strong>
              </div>
              <img :src="snapshot.runtime.camera.frameUrl" :alt="snapshot.runtime.camera.title" />
              <div class="media-card__meta">
                <span>{{ snapshot.runtime.camera.fps }} FPS</span>
                <span>{{ snapshot.runtime.camera.latencyMs }} ms</span>
              </div>
            </article>

            <article class="radar-card">
              <span>雷达覆盖</span>
              <strong>{{ snapshot.runtime.lidar.points.length }} 点</strong>
              <small>最大量程 {{ snapshot.runtime.lidar.maxRangeM.toFixed(1) }} m</small>
            </article>
          </div>
        </div>

        <div class="stage__footer">
          <button
            v-for="zone in selectableZones"
            :key="zone.id"
            class="zone-chip"
            :class="{ 'zone-chip--active': snapshot.runtime.selectedZoneId === zone.id }"
            @click="selectZone(zone.id)"
          >
            {{ zone.name }}
          </button>
        </div>
      </section>

      <aside class="sidebar">
        <section class="panel">
          <div class="panel__head">
            <p class="eyebrow">Mission Control</p>
            <h3>运行控制</h3>
          </div>
          <div class="button-row">
            <button class="action" @click="sendMission('start')">开始巡检</button>
            <button class="action action--ghost" @click="sendMission('pause')">暂停</button>
            <button class="action action--ghost" @click="sendMission('return')">返航</button>
            <button class="action action--ghost" @click="sendMission('clear')">清告警</button>
          </div>
          <p class="panel__copy">{{ snapshot.runtime.mission.objective }}</p>
        </section>

        <section class="panel">
          <div class="panel__head">
            <p class="eyebrow">AI Task</p>
            <h3>AI 指令</h3>
          </div>
          <textarea v-model="aiCommand" rows="4" />
          <button class="action action--wide" @click="submitAiCommand">提交给小车执行</button>
        </section>

        <section class="panel">
          <div class="panel__head">
            <p class="eyebrow">Voice</p>
            <h3>语音链路</h3>
          </div>
          <div class="voice-state">
            <span class="voice-lamp" :class="{ 'voice-lamp--live': voiceStatus?.enabled }" />
            <div>
              <strong>{{ voiceStatus ? voiceStatus.state : '语音状态未知' }}</strong>
              <p>唤醒词：你好贾维斯</p>
            </div>
          </div>
          <p class="panel__copy">{{ voiceStatus?.last_error?.message ?? '状态由本机语音服务上报' }}</p>
          <label class="voice-toggle"><input v-model="ttsEnabled" type="checkbox" /> 语音开关</label>
          <textarea v-model="ttsText" rows="2" placeholder="输入文本，使用本地 Piper 播放" />
          <button class="action action--wide" :disabled="!ttsEnabled || !ttsText.trim()" @click="speakText">生成 TTS 语音</button>
          <p v-if="ttsMessage" class="panel__copy">{{ ttsMessage }}</p>
        </section>

        <section class="panel panel--compact">
          <div class="panel__head">
            <p class="eyebrow">Telemetry</p>
            <h3>设备状态</h3>
          </div>
          <div class="metric-grid">
            <article>
              <span>CPU</span>
              <strong>{{ Math.round(snapshot.runtime.telemetry.cpuPercent) }}%</strong>
            </article>
            <article>
              <span>温度</span>
              <strong>{{ snapshot.runtime.telemetry.temperatureC.toFixed(1) }}℃</strong>
            </article>
            <article>
              <span>电机电流</span>
              <strong>{{ snapshot.runtime.telemetry.motorCurrentA.toFixed(1) }} A</strong>
            </article>
            <article>
              <span>速度</span>
              <strong>{{ snapshot.runtime.robotPose.linearVelocity.toFixed(2) }} m/s</strong>
            </article>
          </div>
        </section>

        <section class="panel panel--compact">
          <div class="panel__head">
            <p class="eyebrow">Zones & Walls</p>
            <h3>区域与虚拟墙</h3>
          </div>
          <div class="selected-zone">
            <span>当前区域</span>
            <strong>{{ selectedZone?.name ?? '未选择' }}</strong>
          </div>
          <div class="wall-list">
            <label v-for="wall in snapshot.world.virtualWalls" :key="wall.id" class="wall-row">
              <input type="checkbox" :checked="wall.enabled" @change="toggleWall(wall.id)" />
              <span>{{ wall.name }}</span>
            </label>
          </div>
        </section>

        <section class="panel panel--compact">
          <div class="panel__head">
            <p class="eyebrow">Task Queue</p>
            <h3>任务队列</h3>
          </div>
          <div class="task-list">
            <article v-for="task in snapshot.runtime.tasks" :key="task.id" class="task-row">
              <div>
                <strong>{{ task.title }}</strong>
                <small>{{ task.status }}</small>
              </div>
              <span>{{ task.progressPct }}%</span>
            </article>
          </div>
        </section>
      </aside>
    </main>
  </div>
</template>
