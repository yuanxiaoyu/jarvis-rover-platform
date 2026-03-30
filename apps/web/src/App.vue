<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  advanceMockRuntime,
  buildNavigationPath,
  createConversationMessage,
  createMappedWorldModel,
  createMockSnapshot,
  createPatrolPath,
  findZoneAtPoint,
  getZoneAnchor,
} from '@/data/mockWorld'
import { RoverScene } from '@/lib/roverScene'
import type { RoverSnapshot, TaskItem, Vec2, VirtualWall } from '@/types/contract'

const iconPaths = {
  task:
    'M5 6.5h14M5 12h14M5 17.5h9M7.5 4.5v15M16.5 4.5v15M5 4.5h14v15H5z',
  layers:
    'M12 4 20 8.5 12 13 4 8.5 12 4zm0 9 8 4.5-8 4.5-8-4.5 8-4.5zm0-4.5 8 4.5',
  play: 'M8 6.5v11l9-5.5-9-5.5z',
  pause: 'M8.5 6.5v11M15.5 6.5v11',
  home: 'M5.5 11.5 12 6l6.5 5.5M7.5 10.5v8h9v-8',
  clear: 'M7 7l10 10M17 7 7 17M12 3.5v2M12 18.5v2',
  mic: 'M12 4.5a2.8 2.8 0 0 1 2.8 2.8v4.4a2.8 2.8 0 0 1-5.6 0V7.3A2.8 2.8 0 0 1 12 4.5zm-5 7.2a5 5 0 0 0 10 0M12 17v3M9 20h6',
  send: 'M4.5 12 19 5.5l-3 13-4.5-4.2-3.7 2 1.8-5.4L4.5 12z',
  route:
    'M6 17.5c0-1.7 1.3-3 3-3s3 1.3 3 3-1.3 3-3 3-3-1.3-3-3zm6-11c0-1.7 1.3-3 3-3s3 1.3 3 3-1.3 3-3 3-3-1.3-3-3zm-1 1.5H8.5a3 3 0 0 0 0 6H12a3 3 0 0 1 0 6h-1.5',
  scan:
    'M7 4.5H5.5v3M17 4.5h1.5v3M7 19.5H5.5v-3M18.5 16.5v3H17M9 12h6M12 9v6M4.5 9V7a2.5 2.5 0 0 1 2.5-2.5h2M19.5 9V7A2.5 2.5 0 0 0 17 4.5h-2M4.5 15v2A2.5 2.5 0 0 0 7 19.5h2M19.5 15v2a2.5 2.5 0 0 1-2.5 2.5h-2',
  wall:
    'M6.5 17.5h11M7.5 6.5l9 11M6.5 7.5h11M6.5 12h11M8 4.5v3M16 16.5v3',
  chat:
    'M6.5 7.5h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-6l-4.5 3v-3h-.5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2zm2.5 4h6M9 12.5h4',
  battery:
    'M6 8h11v8H6zM19 10h1v4h-1M8 10.5h4.5v3H8z',
  signal:
    'M5.5 17.5h2v-3h-2v3zm4 0h2v-6h-2v6zm4 0h2v-9h-2v9zm4 0h2V6.5h-2v11z',
  cpu:
    'M9 3.5v2M15 3.5v2M9 18.5v2M15 18.5v2M3.5 9h2M3.5 15h2M18.5 9h2M18.5 15h2M8 6.5h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 16 17.5H8A1.5 1.5 0 0 1 6.5 16V8A1.5 1.5 0 0 1 8 6.5zm1.5 3h5v5h-5z',
  thermo:
    'M10 6.5a2 2 0 1 1 4 0v6.2a4 4 0 1 1-4 0V6.5zm2 6.5v3',
  speed:
    'M6 16.5a8 8 0 1 1 12 0M12 12l4-2M12 12l-2.5 4.5M7 16.5h10',
  current:
    'M13.5 3.5 7.5 12h3l-1 8.5 6-8h-3l1-9z',
  collapse:
    'M6.5 9.5 12 15l5.5-5.5',
  target:
    'M12 4.5v3M12 16.5v3M4.5 12h3M16.5 12h3M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z',
  timer:
    'M12 6.5v5l3 2M9 3.5h6M12 20a8 8 0 1 1 0-16 8 8 0 0 1 0 16z',
  plus: 'M12 5.5v13M5.5 12h13',
  trash:
    'M8 7.5V6a1.5 1.5 0 0 1 1.5-1.5h5A1.5 1.5 0 0 1 16 6v1.5M5.5 7.5h13M8 10.5v6M12 10.5v6M16 10.5v6M7 7.5l.8 11a1.5 1.5 0 0 0 1.5 1.4h5.4a1.5 1.5 0 0 0 1.5-1.4l.8-11',
} as const

type IconName = keyof typeof iconPaths
type DialogName = 'tasks' | 'assets'

const IconGlyph = defineComponent({
  name: 'IconGlyph',
  props: {
    name: {
      type: String,
      required: true,
    },
  },
  setup(props) {
    return () => {
      const iconName = props.name as IconName
      return h(
        'svg',
        {
          viewBox: '0 0 24 24',
          'aria-hidden': 'true',
        },
        [
          h('path', {
            d: iconPaths[iconName],
            fill: 'none',
            stroke: 'currentColor',
            'stroke-width': '1.7',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
          }),
        ],
      )
    }
  },
})

const missionModeLabels = {
  idle: '待命',
  autonomy: '自主运行',
  manual: '手动接管',
  paused: '已暂停',
  returning: '返航中',
  scanning: '建图扫描',
} as const

const taskStatusLabels = {
  queued: '排队中',
  running: '执行中',
  blocked: '阻塞',
  done: '完成',
} as const

const mappingStatusLabels = {
  unmapped: '未建模',
  scanning: '扫描中',
  ready: '已建模',
} as const

const snapshot = ref<RoverSnapshot>(createMockSnapshot())
const aiCommand = ref('贾维斯，建图完成后去东侧巡检区巡检并回传状态。')
const sceneHost = ref<HTMLDivElement | null>(null)
const activeDialog = ref<DialogName | null>(null)
const chatCollapsed = ref(true)
const drawWallMode = ref(false)
const waypointMode = ref(false)
const labelPlacementMode = ref(false)
const labelPlacementTargetId = ref<string | null>(null)
const customWaypoints = ref<Vec2[]>([])
const draftWallStart = ref<Vec2 | null>(null)
const draftWallHover = ref<Vec2 | null>(null)
const newLabelName = ref('')

let scene: RoverScene | null = null
let timer: number | null = null
let tick = 0

const selectedZone = computed(
  () => snapshot.value.world.zones.find((zone) => zone.id === snapshot.value.runtime.selectedZoneId) ?? null,
)
const mappingReady = computed(() => snapshot.value.world.mapping.status === 'ready')
const enabledWalls = computed(() => snapshot.value.world.virtualWalls.filter((wall) => wall.enabled).length)
const activeTask = computed(
  () => snapshot.value.runtime.tasks.find((task) => task.status === 'running') ?? snapshot.value.runtime.tasks[0] ?? null,
)
const visibleMessages = computed(() => snapshot.value.runtime.conversationHistory.slice(-8))
const chatMessageCount = computed(() => snapshot.value.runtime.conversationHistory.length)
const compactTaskLabel = computed(() => {
  const title = activeTask.value?.title ?? '暂无'
  return title.length > 8 ? `${title.slice(0, 8)}...` : title
})
const compactDestinationLabel = computed(() => {
  const text = destinationSummary.value
  return text.length > 8 ? `${text.slice(0, 8)}...` : text
})
const hasPlannedPath = computed(
  () => snapshot.value.runtime.path.status === 'planned' && snapshot.value.runtime.path.waypoints.length > 1,
)
const activeRouteLabel = computed(() => {
  const ids = snapshot.value.runtime.path.waypoints.length > 1 ? snapshot.value.runtime.path.waypoints.length : 0
  if (snapshot.value.runtime.path.destination && selectedZone.value) {
    return `${selectedZone.value.name} / ${ids} 点`
  }
  if (snapshot.value.runtime.path.destination) {
    return `${destinationSummary.value} / ${ids} 点`
  }
  return ids > 0 ? `${ids} 点路径` : '待规划'
})
const routeDistanceLabel = computed(() => {
  const points = snapshot.value.runtime.path.waypoints
  if (points.length < 2) {
    return '0.0 m'
  }

  let total = 0
  for (let index = 1; index < points.length; index += 1) {
    total += Math.hypot(points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
  }
  return `${total.toFixed(1)} m`
})
const destinationSummary = computed(() => {
  const destination = snapshot.value.runtime.path.destination
  if (!destination) {
    return '未设置'
  }

  const zone = findZoneAtPoint(snapshot.value.world, destination)
  if (zone) {
    return zone.name
  }

  return `${destination[0].toFixed(1)}m, ${destination[1].toFixed(1)}m`
})
const operationHint = computed(() => {
  if (snapshot.value.world.mapping.status === 'unmapped') {
    return '工作区尚未建模，先执行一键全屋扫描。'
  }

  if (snapshot.value.world.mapping.status === 'scanning') {
    return '小车正在全屋自动避障扫描，地图会在完成后自动生成。'
  }

  if (labelPlacementMode.value) {
    return '标签放置模式已开启，请在画布中点击标签展示位置。'
  }

  if (waypointMode.value) {
    return customWaypoints.value.length > 0
      ? '已添加自定义节点，右击终点后生成多段路径。'
      : '节点规划模式已开启，请左键依次添加行驶节点。'
  }

  if (drawWallMode.value && !draftWallStart.value) {
    return '虚拟墙绘制模式已开启，请在地图上左键设置起点。'
  }

  if (drawWallMode.value && draftWallStart.value) {
    return '请继续左键设置终点，系统会立即生成新的隔离线。'
  }

  return ''
})
const draftWallPreview = computed(() => {
  if (!drawWallMode.value || !draftWallStart.value) {
    return null
  }

  return {
    start: draftWallStart.value,
    end: draftWallHover.value,
  }
})

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`
}

function nextRegionLabelName(): string {
  const used = snapshot.value.world.regionLabels
    .map((label) => /^新增标签(\d+)$/.exec(label.name)?.[1])
    .filter((value): value is string => Boolean(value))
    .map((value) => Number(value))

  const next = used.length > 0 ? Math.max(...used) + 1 : 1
  return `新增标签${next}`
}

function updateStatusLine(message: string): void {
  snapshot.value.runtime.mission.statusLine = message
}

function syncSceneWorld(): void {
  scene?.setWorld(snapshot.value.world)
  scene?.setRuntime(snapshot.value.runtime)
  scene?.setWaypointDraft(customWaypoints.value)
  syncDraftWall()
}

function syncSceneRuntime(): void {
  scene?.setRuntime(snapshot.value.runtime)
  scene?.setWaypointDraft(customWaypoints.value)
}

function syncDraftWall(): void {
  scene?.setDraftWall(draftWallPreview.value)
}

function appendConversation(role: 'user' | 'assistant' | 'system', content: string): void {
  snapshot.value.runtime.conversationHistory = [
    ...snapshot.value.runtime.conversationHistory,
    createConversationMessage(role, content),
  ].slice(-30)
}

function upsertTask(task: TaskItem): void {
  const index = snapshot.value.runtime.tasks.findIndex((item) => item.id === task.id)
  if (index >= 0) {
    snapshot.value.runtime.tasks.splice(index, 1, task)
    return
  }

  snapshot.value.runtime.tasks = [task, ...snapshot.value.runtime.tasks].slice(0, 8)
}

function finishTask(taskId: string): void {
  snapshot.value.runtime.tasks = snapshot.value.runtime.tasks.map((task) =>
    task.id === taskId ? { ...task, status: 'done', progressPct: 100, etaSec: 0 } : task,
  )
}

function selectZone(zoneId: string): void {
  snapshot.value.runtime.selectedZoneId = zoneId
  const zone = snapshot.value.world.zones.find((item) => item.id === zoneId)
  updateStatusLine(zone ? `已锁定区域：${zone.name}` : '已更新区域焦点')
  syncSceneRuntime()
}

function startWholeHomeScan(source: 'button' | 'chat' = 'button'): void {
  if (snapshot.value.world.mapping.status === 'scanning') {
    updateStatusLine('全屋扫描已在执行中。')
    return
  }

  if (snapshot.value.world.mapping.status === 'ready') {
    updateStatusLine('当前地图已完成建模，可直接导航或编辑区域。')
    if (source === 'chat') {
      appendConversation('assistant', '当前地图已经完成建模，可以直接右键导航或编辑区域标签。')
    }
    return
  }

  snapshot.value.world.mapping.status = 'scanning'
  snapshot.value.world.mapping.progressPct = 0
  snapshot.value.world.mapping.hint = '全屋自动避障扫描进行中，地图建模完成后会自动解锁交互。'
  snapshot.value.runtime.mission.mode = 'scanning'
  snapshot.value.runtime.mission.objective = '一键全屋扫描建模'
  snapshot.value.runtime.path = {
    id: 'path-scan',
    status: 'planned',
    waypoints: [],
    destination: null,
    algorithm: '全屋自动避障扫描',
    lastUpdatedMs: Date.now(),
  }
  updateStatusLine('一键全屋扫描已启动，小车正在执行自动避障建模。')
  upsertTask({
    id: 'task-map',
    title: '全屋自动避障扫描建图',
    status: 'running',
    progressPct: 1,
    etaSec: 180,
  })
  appendConversation(
    source === 'chat' ? 'assistant' : 'system',
    '已启动一键全屋扫描，小车会自动避障并生成首版工作区地图。',
  )
  syncSceneWorld()
}

function completeWholeHomeScan(): void {
  snapshot.value.world = createMappedWorldModel()
  snapshot.value.runtime.selectedZoneId = 'atrium-core'
  snapshot.value.runtime.mission.mode = 'idle'
  snapshot.value.runtime.mission.objective = '建模完成，等待下一步任务'
  snapshot.value.runtime.path = {
    id: 'path-idle',
    status: 'idle',
    waypoints: [],
    destination: null,
    algorithm: '待命',
    lastUpdatedMs: Date.now(),
  }
  finishTask('task-map')
  updateStatusLine('整屋扫描完成，地图已生成。现在可以右键导航和绘制虚拟墙。')
  appendConversation('assistant', '整屋扫描完成，地图与区域已生成。右键地图即可设置目的地。')
  syncSceneWorld()
}

function navigateTo(destination: Vec2, sourceLabel = '右键导航'): void {
  if (!mappingReady.value) {
    updateStatusLine('地图尚未建模，请先执行全屋扫描。')
    return
  }

  const start: Vec2 = [snapshot.value.runtime.robotPose.x, snapshot.value.runtime.robotPose.y]
  const path = buildNavigationPath(snapshot.value.world, start, destination)
  if (path.length < 2) {
    updateStatusLine('当前目标不可达，请调整目标点或虚拟墙。')
    appendConversation('system', '导航目标不可达，可能被限制区或虚拟墙阻断。')
    return
  }

  const zone = findZoneAtPoint(snapshot.value.world, destination)
  const targetLabel = zone?.name ?? `${destination[0].toFixed(1)}m, ${destination[1].toFixed(1)}m`

  snapshot.value.runtime.selectedZoneId = zone?.id ?? snapshot.value.runtime.selectedZoneId
  snapshot.value.runtime.path = {
    id: `goto-${Date.now()}`,
    status: 'executing',
    waypoints: path,
    destination,
    algorithm: 'A* + 虚拟墙避让',
    lastUpdatedMs: Date.now(),
  }
  snapshot.value.runtime.mission.mode = 'autonomy'
  snapshot.value.runtime.mission.objective = `导航至 ${targetLabel}`
  updateStatusLine(`已规划导航路径，正在前往 ${targetLabel}`)
  upsertTask({
    id: 'task-navigation',
    title: `导航至 ${targetLabel}`,
    status: 'running',
    progressPct: 6,
    etaSec: Math.max(45, Math.round(path.length * 18)),
  })
  appendConversation('user', `${sourceLabel}：前往 ${targetLabel}`)
  appendConversation('assistant', `已生成 ${path.length} 个路径点，小车开始自动导航。`)
  syncSceneRuntime()
}

function planRouteTo(destination: Vec2, sourceLabel = '右键规划'): void {
  if (!mappingReady.value) {
    updateStatusLine('地图尚未建模，请先执行全屋扫描。')
    return
  }

  const start: Vec2 = [snapshot.value.runtime.robotPose.x, snapshot.value.runtime.robotPose.y]
  const path = buildNavigationPath(snapshot.value.world, start, destination)
  if (path.length < 2) {
    updateStatusLine('当前目标不可达，请调整目标点或虚拟墙。')
    appendConversation('system', '规划目标不可达，可能被限制区或虚拟墙阻断。')
    return
  }

  const zone = findZoneAtPoint(snapshot.value.world, destination)
  const targetLabel = zone?.name ?? `${destination[0].toFixed(1)}m, ${destination[1].toFixed(1)}m`

  snapshot.value.runtime.selectedZoneId = zone?.id ?? snapshot.value.runtime.selectedZoneId
  snapshot.value.runtime.path = {
    id: `goto-${Date.now()}`,
    status: 'planned',
    waypoints: path,
    destination,
    algorithm: 'A* + 虚拟墙避让',
    lastUpdatedMs: Date.now(),
  }
  snapshot.value.runtime.mission.mode = 'idle'
  snapshot.value.runtime.mission.objective = `已规划至 ${targetLabel}`
  updateStatusLine(`已规划到 ${targetLabel} 的路径，请点击执行按钮开始。`)
  upsertTask({
    id: 'task-navigation',
    title: `已规划至 ${targetLabel}`,
    status: 'queued',
    progressPct: 0,
    etaSec: Math.max(45, Math.round(path.length * 18)),
  })
  appendConversation('user', `${sourceLabel}：${targetLabel}`)
  appendConversation('assistant', `路径已规划完成，共 ${path.length} 个路径点，等待执行。`)
  syncSceneRuntime()
}

function executePlannedPath(): void {
  if (!hasPlannedPath.value) {
    return
  }

  snapshot.value.runtime.path = {
    ...snapshot.value.runtime.path,
    status: 'executing',
    lastUpdatedMs: Date.now(),
  }
  snapshot.value.runtime.mission.mode = 'autonomy'
  updateStatusLine('已开始执行规划路径。')
  snapshot.value.runtime.tasks = snapshot.value.runtime.tasks.map((task) =>
    task.id === 'task-navigation' ? { ...task, status: 'running', progressPct: Math.max(task.progressPct, 6) } : task,
  )
  appendConversation('assistant', '已执行规划路径，小车开始移动。')
  syncSceneRuntime()
}

function refreshPathAfterKeepoutChange(): void {
  if (!mappingReady.value) {
    return
  }

  if (snapshot.value.runtime.path.id.startsWith('goto') && snapshot.value.runtime.path.destination) {
    navigateTo(snapshot.value.runtime.path.destination, '虚拟墙重规划')
    return
  }

  if (snapshot.value.runtime.path.id.startsWith('patrol')) {
    snapshot.value.runtime.path = {
      ...snapshot.value.runtime.path,
      waypoints: createPatrolPath(snapshot.value.world),
      status: 'executing',
      lastUpdatedMs: Date.now(),
    }
    updateStatusLine('巡检路线已按最新虚拟墙重规划。')
    syncSceneRuntime()
  }
}

function startPatrol(): void {
  if (!mappingReady.value) {
    startWholeHomeScan()
    return
  }

  const patrolPath = createPatrolPath(snapshot.value.world)
  if (patrolPath.length < 2) {
    return
  }

  snapshot.value.runtime.path = {
    id: 'patrol-loop',
    status: 'executing',
    waypoints: patrolPath,
    destination: null,
    algorithm: '巡检环线',
    lastUpdatedMs: Date.now(),
  }
  snapshot.value.runtime.mission.mode = 'autonomy'
  snapshot.value.runtime.mission.objective = '自主巡检'
  updateStatusLine('自主巡检已启动，小车会沿环线持续巡航。')
  upsertTask({
    id: 'task-patrol',
    title: '自主巡检',
    status: 'running',
    progressPct: 5,
    etaSec: 360,
  })
  appendConversation('assistant', '已启动自主巡检，地图会持续显示实时轨迹。')
  syncSceneRuntime()
}

function pauseMission(): void {
  snapshot.value.runtime.mission.mode = 'paused'
  snapshot.value.runtime.path = {
    ...snapshot.value.runtime.path,
    status: snapshot.value.runtime.path.waypoints.length > 0 ? 'paused' : snapshot.value.runtime.path.status,
    lastUpdatedMs: Date.now(),
  }
  updateStatusLine('任务已暂停，当前路径保留。')
  appendConversation('assistant', '当前任务已暂停，路径和目标点仍然保留。')
  syncSceneRuntime()
}

function returnHome(): void {
  if (!mappingReady.value) {
    updateStatusLine('地图尚未建模，无法返航。')
    return
  }

  const dock = getZoneAnchor(snapshot.value.world, 'dock-west')
  if (!dock) {
    return
  }

  navigateTo(dock, '返航指令')
  snapshot.value.runtime.mission.mode = 'returning'
  snapshot.value.runtime.mission.objective = '返航回桩'
  updateStatusLine('返航回桩已下发，小车正在返回停靠区。')
  upsertTask({
    id: 'task-return',
    title: '返航回桩',
    status: 'running',
    progressPct: 8,
    etaSec: 120,
  })
  syncSceneRuntime()
}

function clearAlerts(): void {
  snapshot.value.runtime.tasks = snapshot.value.runtime.tasks.map((task) =>
    task.status === 'blocked' ? { ...task, status: 'queued' } : task,
  )
  updateStatusLine('告警与阻塞状态已清理。')
  appendConversation('system', '告警队列已清理。')
}

function toggleVoice(): void {
  snapshot.value.runtime.voice.listening = !snapshot.value.runtime.voice.listening
  snapshot.value.runtime.voice.transcript = snapshot.value.runtime.voice.listening
    ? '正在听取指令，请直接说出任务。'
    : '语音待命中，可直接与小车对话。'
  snapshot.value.runtime.voice.confidence = snapshot.value.runtime.voice.listening ? 0.94 : 0
  appendConversation(
    'assistant',
    snapshot.value.runtime.voice.listening ? '语音会话已开启。' : '语音会话已关闭，仍可继续查看历史记录。',
  )
}

function submitAiCommand(): void {
  const prompt = aiCommand.value.trim()
  if (!prompt) {
    return
  }

  appendConversation('user', prompt)

  if (prompt.includes('扫描') && !mappingReady.value) {
    startWholeHomeScan('chat')
    aiCommand.value = ''
    return
  }

  if (prompt.includes('返航') || prompt.includes('回桩')) {
    returnHome()
    aiCommand.value = ''
    return
  }

  if (prompt.includes('暂停')) {
    pauseMission()
    aiCommand.value = ''
    return
  }

  const zone = snapshot.value.world.zones.find((item) => prompt.includes(item.name))
  if (zone) {
    const anchor = getZoneAnchor(snapshot.value.world, zone.id)
    if (anchor) {
      navigateTo(anchor, 'AI 指令')
      aiCommand.value = ''
      return
    }
  }

  upsertTask({
    id: createId('ai-task'),
    title: prompt.length > 18 ? `${prompt.slice(0, 18)}...` : prompt,
    status: 'queued',
    progressPct: 0,
    etaSec: 240,
  })
  updateStatusLine(mappingReady.value ? 'AI 指令已进入任务队列。' : 'AI 指令已记录，建议先执行建图。')
  appendConversation(
    'assistant',
    mappingReady.value
      ? '已记录对话并加入任务队列。你也可以直接右键地图设置目的地。'
      : '已记录指令，但当前地图尚未建模，建议先执行全屋扫描。',
  )
  aiCommand.value = ''
}

function openDialog(name: DialogName): void {
  activeDialog.value = name
}

function closeDialog(): void {
  activeDialog.value = null
}

function openChatPanel(): void {
  chatCollapsed.value = false
}

function closeChatPanel(): void {
  chatCollapsed.value = true
}

function beginLabelPlacement(labelId: string | null = null): void {
  if (!mappingReady.value) {
    updateStatusLine('请先完成建图后再设置区域标签。')
    return
  }

  activeDialog.value = null
  drawWallMode.value = false
  draftWallStart.value = null
  draftWallHover.value = null
  waypointMode.value = false
  customWaypoints.value = []
  labelPlacementMode.value = true
  labelPlacementTargetId.value = labelId

  if (!labelId && !newLabelName.value.trim()) {
    newLabelName.value = nextRegionLabelName()
  }

  if (labelId) {
    updateStatusLine('标签重定位模式已开启，请在画布中点击新的标签位置。')
  } else {
    updateStatusLine('标签放置模式已开启，请在画布中点击标签展示位置。')
  }
  syncDraftWall()
  syncSceneRuntime()
}

function cancelLabelPlacement(): void {
  labelPlacementMode.value = false
  labelPlacementTargetId.value = null
  updateStatusLine('已退出标签放置模式。')
}

function beginWallDrawing(): void {
  if (!mappingReady.value) {
    updateStatusLine('请先完成建图后再绘制虚拟墙。')
    return
  }

  activeDialog.value = null
  waypointMode.value = false
  customWaypoints.value = []
  drawWallMode.value = true
  draftWallStart.value = null
  draftWallHover.value = null
  updateStatusLine('虚拟墙绘制模式已开启，请在地图上依次点击起点和终点。')
  appendConversation('assistant', '已进入虚拟墙绘制模式，请在地图上点击两点完成隔离线。')
  syncDraftWall()
}

function cancelWallDrawing(): void {
  drawWallMode.value = false
  draftWallStart.value = null
  draftWallHover.value = null
  updateStatusLine('已退出虚拟墙绘制模式。')
  syncDraftWall()
}

function beginWaypointMode(): void {
  if (!mappingReady.value) {
    updateStatusLine('请先完成建图后再规划自定义节点。')
    return
  }

  activeDialog.value = null
  drawWallMode.value = false
  draftWallStart.value = null
  draftWallHover.value = null
  waypointMode.value = true
  customWaypoints.value = []
  updateStatusLine('节点规划模式已开启，请左键添加节点，右击终点完成路径。')
  appendConversation('assistant', '已进入自定义节点模式，左键添加节点，右击终点生成路径。')
  syncSceneRuntime()
  syncDraftWall()
}

function cancelWaypointMode(): void {
  waypointMode.value = false
  customWaypoints.value = []
  updateStatusLine('已退出自定义节点模式。')
  syncSceneRuntime()
}

function buildPathWithWaypoints(start: Vec2, nodes: Vec2[], destination: Vec2): Vec2[] {
  const sequence = [...nodes, destination]
  let current = start
  const merged: Vec2[] = [start]

  for (const node of sequence) {
    const segment = buildNavigationPath(snapshot.value.world, current, node)
    if (segment.length < 2) {
      return []
    }

    merged.push(...segment.slice(1))
    current = node
  }

  return merged
}

function navigateWithCustomWaypoints(destination: Vec2): void {
  const start: Vec2 = [snapshot.value.runtime.robotPose.x, snapshot.value.runtime.robotPose.y]
  const path = buildPathWithWaypoints(start, customWaypoints.value, destination)
  if (path.length < 2) {
    updateStatusLine('节点路径不可达，请调整节点或虚拟墙。')
    appendConversation('system', '自定义节点路径不可达，请重新设置节点。')
    return
  }

  const zone = findZoneAtPoint(snapshot.value.world, destination)
  const targetLabel = zone?.name ?? `${destination[0].toFixed(1)}m, ${destination[1].toFixed(1)}m`
  snapshot.value.runtime.selectedZoneId = zone?.id ?? snapshot.value.runtime.selectedZoneId
  snapshot.value.runtime.path = {
    id: `goto-${Date.now()}`,
    status: 'planned',
    waypoints: path,
    destination,
    algorithm: `节点规划 ${customWaypoints.value.length} 段`,
    lastUpdatedMs: Date.now(),
  }
  snapshot.value.runtime.mission.mode = 'idle'
  snapshot.value.runtime.mission.objective = `已规划 ${customWaypoints.value.length} 节点至 ${targetLabel}`
  updateStatusLine(`已生成 ${customWaypoints.value.length} 个自定义节点路径，请点击执行按钮开始。`)
  upsertTask({
    id: 'task-navigation',
    title: `节点路径至 ${targetLabel}`,
    status: 'queued',
    progressPct: 0,
    etaSec: Math.max(50, Math.round(path.length * 18)),
  })
  appendConversation('assistant', `已按 ${customWaypoints.value.length} 个节点生成路径，等待执行。`)
  waypointMode.value = false
  customWaypoints.value = []
  syncSceneRuntime()
}

function handleMapPrimary(point: Vec2): void {
  if (labelPlacementMode.value && mappingReady.value) {
    const targetLabel = labelPlacementTargetId.value
      ? snapshot.value.world.regionLabels.find((label) => label.id === labelPlacementTargetId.value) ?? null
      : null
    const zoneAtPoint = findZoneAtPoint(snapshot.value.world, point)
    const zoneId =
      targetLabel?.zoneId ??
      snapshot.value.runtime.selectedZoneId ??
      zoneAtPoint?.id ??
      null

    if (!zoneId) {
      updateStatusLine('请先选择一个区域，再点击画布放置标签。')
      return
    }

    const name = targetLabel?.name || newLabelName.value.trim() || nextRegionLabelName()
    const nextId = targetLabel?.id ?? createId('label')

    snapshot.value.world.regionLabels = [
      ...snapshot.value.world.regionLabels.filter((label) => label.id !== nextId),
      {
        id: nextId,
        name,
        position: point,
        zoneId,
      },
    ]

    newLabelName.value = ''
    labelPlacementMode.value = false
    labelPlacementTargetId.value = null
    updateStatusLine(`已保存区域标签：${name}`)
    appendConversation('system', `已保存区域标签：${name}`)
    syncSceneWorld()
    return
  }

  if (waypointMode.value && mappingReady.value) {
    customWaypoints.value = [...customWaypoints.value, point]
    updateStatusLine(`已添加节点 ${customWaypoints.value.length} (${point[0].toFixed(1)}, ${point[1].toFixed(1)})`)
    syncSceneRuntime()
    return
  }

  if (!drawWallMode.value || !mappingReady.value) {
    return
  }

  if (!draftWallStart.value) {
    draftWallStart.value = point
    draftWallHover.value = point
    updateStatusLine(`已记录虚拟墙起点 (${point[0].toFixed(1)}, ${point[1].toFixed(1)})`)
    syncDraftWall()
    return
  }

  const wall: VirtualWall = {
    id: createId('wall'),
    name: `虚拟墙 ${snapshot.value.world.virtualWalls.length + 1}`,
    start: draftWallStart.value,
    end: point,
    height: 1.1,
    enabled: true,
  }

  snapshot.value.world.virtualWalls = [...snapshot.value.world.virtualWalls, wall]
  drawWallMode.value = false
  draftWallStart.value = null
  draftWallHover.value = null
  updateStatusLine(`已新增虚拟墙：${wall.name}`)
  appendConversation('assistant', `已创建 ${wall.name}，新的导航路径会自动避让该线段。`)
  syncSceneWorld()
  refreshPathAfterKeepoutChange()
}

function handleMapHover(point: Vec2 | null): void {
  if (!drawWallMode.value || !draftWallStart.value) {
    return
  }

  draftWallHover.value = point
  syncDraftWall()
}

function handleMapSecondary(point: Vec2): void {
  if (!mappingReady.value) {
    updateStatusLine('地图为空，请先执行全屋扫描。')
    return
  }

  if (waypointMode.value) {
    navigateWithCustomWaypoints(point)
    return
  }

  if (drawWallMode.value) {
    updateStatusLine('当前处于虚拟墙绘制模式，请继续使用左键完成绘制。')
    return
  }

  planRouteTo(point)
}

function addRegionLabel(): void {
  if (!mappingReady.value) {
    return
  }

  beginLabelPlacement()
}

function upsertRegionLabelForZone(zoneId: string, name?: string): void {
  const anchor = getZoneAnchor(snapshot.value.world, zoneId)
  if (!anchor) {
    return
  }

  const nextName = name?.trim() || nextRegionLabelName()
  const position: Vec2 = [anchor[0], anchor[1]]

  snapshot.value.world.regionLabels = [
    ...snapshot.value.world.regionLabels,
    {
      id: createId('label'),
      name: nextName,
      position,
      zoneId,
    },
  ]

  updateStatusLine(`已新增区域标签：${nextName}`)
  appendConversation('system', `已新增区域标签：${nextName}`)
  syncSceneWorld()
}

function renameRegionLabel(labelId: string, event: Event): void {
  const value = (event.target as HTMLInputElement).value.trim()
  snapshot.value.world.regionLabels = snapshot.value.world.regionLabels.map((label) =>
    label.id === labelId ? { ...label, name: value || label.name } : label,
  )
  syncSceneWorld()
}

function removeRegionLabel(labelId: string): void {
  snapshot.value.world.regionLabels = snapshot.value.world.regionLabels.filter((label) => label.id !== labelId)
  syncSceneWorld()
}

function toggleWall(wallId: string): void {
  snapshot.value.world.virtualWalls = snapshot.value.world.virtualWalls.map((wall) =>
    wall.id === wallId ? { ...wall, enabled: !wall.enabled } : wall,
  )
  updateStatusLine('虚拟墙配置已更新。')
  syncSceneWorld()
  refreshPathAfterKeepoutChange()
}

function renameWall(wallId: string, event: Event): void {
  const value = (event.target as HTMLInputElement).value.trim()
  snapshot.value.world.virtualWalls = snapshot.value.world.virtualWalls.map((wall) =>
    wall.id === wallId ? { ...wall, name: value || wall.name } : wall,
  )
  syncSceneWorld()
}

function removeWall(wallId: string): void {
  snapshot.value.world.virtualWalls = snapshot.value.world.virtualWalls.filter((wall) => wall.id !== wallId)
  updateStatusLine('虚拟墙已删除。')
  syncSceneWorld()
  refreshPathAfterKeepoutChange()
}

function tickRuntime(): void {
  tick += 1

  if (snapshot.value.world.mapping.status === 'scanning') {
    const nextProgress = Math.min(100, snapshot.value.world.mapping.progressPct + 6)
    snapshot.value.world.mapping.progressPct = nextProgress
    snapshot.value.world.mapping.hint = `全屋自动避障扫描进行中 ${nextProgress}%`
    updateStatusLine(`全屋自动避障扫描中，正在重建工作区 ${nextProgress}%`)
    upsertTask({
      id: 'task-map',
      title: '全屋自动避障扫描建图',
      status: nextProgress >= 100 ? 'done' : 'running',
      progressPct: nextProgress,
      etaSec: Math.max(0, Math.round((100 - nextProgress) * 1.7)),
    })

    if (nextProgress >= 100) {
      completeWholeHomeScan()
    }
  }

  const previousPathStatus = snapshot.value.runtime.path.status
  const previousPathId = snapshot.value.runtime.path.id
  snapshot.value.runtime = advanceMockRuntime(snapshot.value.runtime, snapshot.value.world, tick)

  if (previousPathStatus !== 'completed' && snapshot.value.runtime.path.status === 'completed') {
    const destination = snapshot.value.runtime.path.destination
    const zone = destination ? findZoneAtPoint(snapshot.value.world, destination) : null
    updateStatusLine(`已到达 ${zone?.name ?? '目标点'}`)
    snapshot.value.runtime.mission.mode = 'idle'
    if (previousPathId.startsWith('goto')) {
      finishTask('task-navigation')
    }
    if (snapshot.value.runtime.mission.objective === '返航回桩') {
      finishTask('task-return')
    }
    appendConversation('assistant', `已到达 ${zone?.name ?? '目标点'}。`)
    snapshot.value.runtime.path = {
      ...snapshot.value.runtime.path,
      destination: null,
    }
  }

  syncSceneRuntime()
}

onMounted(() => {
  if (sceneHost.value) {
    scene = new RoverScene(sceneHost.value, {
      onZoneSelect: (zoneId) => selectZone(zoneId),
      onZoneDoubleClick: (zoneId) => upsertRegionLabelForZone(zoneId),
      onMapPrimaryAction: (point) => handleMapPrimary(point),
      onMapSecondaryAction: (point) => handleMapSecondary(point),
      onMapHover: (point) => handleMapHover(point),
    })
    syncSceneWorld()
  }

  timer = window.setInterval(() => {
    tickRuntime()
  }, 900)
})

onBeforeUnmount(() => {
  if (timer) {
    window.clearInterval(timer)
  }

  scene?.destroy()
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="topbar__title">
        <h1>贾维斯小车一屏控制台</h1>
        <span class="topbar__status">{{ snapshot.runtime.mission.statusLine }}</span>
      </div>

      <div class="topbar__chips">
        <span class="chip">{{ snapshot.world.mapName }}</span>
        <span class="chip chip--accent">{{ missionModeLabels[snapshot.runtime.mission.mode] }}</span>
        <span class="chip">地图 {{ mappingStatusLabels[snapshot.world.mapping.status] }}</span>
        <span class="chip">虚拟墙 {{ enabledWalls }}/{{ snapshot.world.virtualWalls.length }}</span>
      </div>
    </header>

    <main class="workspace">
      <section class="stage">
        <div class="scene-frame">
          <div ref="sceneHost" class="scene-host" />
        </div>

        <div class="stage__cluster stage__cluster--summary">
          <span class="stage__section-label">导航</span>
          <div class="headline-metrics">
            <div class="metric-pill" :title="selectedZone?.name ?? '等待目标区域'">
              <IconGlyph :name="selectedZone?.id === 'dock-west' ? 'home' : 'layers'" />
              <span>{{ selectedZone?.name ?? '待选区' }}</span>
            </div>
            <div class="metric-pill">
              <IconGlyph name="battery" />
              <span>{{ Math.round(snapshot.runtime.telemetry.batteryPercent) }}%</span>
            </div>
            <div class="metric-pill">
              <IconGlyph name="signal" />
              <span>{{ Math.round(snapshot.runtime.telemetry.localizationConfidence * 100) }}%</span>
            </div>
            <div class="metric-pill">
              <IconGlyph name="route" />
              <span>{{ snapshot.runtime.path.algorithm }}</span>
            </div>
          </div>
        </div>

        <div v-if="operationHint || drawWallMode || waypointMode || labelPlacementMode" class="stage__hint">
          <span v-if="operationHint" class="stage__hint-badge">{{ operationHint }}</span>
          <button
            v-if="labelPlacementMode"
            type="button"
            class="stage__hint-action stage__hint-action--icon"
            title="取消标签放置"
            @click="cancelLabelPlacement"
          >
            <IconGlyph name="clear" />
          </button>
          <button
            v-if="drawWallMode"
            type="button"
            class="stage__hint-action"
            @click="cancelWallDrawing"
          >
            退出绘制
          </button>
          <button
            v-if="waypointMode"
            type="button"
            class="stage__hint-action stage__hint-action--icon"
            title="清空节点"
            @click="cancelWaypointMode"
          >
            <IconGlyph name="clear" />
          </button>
        </div>

        <div class="stage__cluster stage__cluster--tools">
          <span class="stage__section-label">工具</span>
          <div class="toolbar">
            <button type="button" class="icon-button" title="任务队列" @click="openDialog('tasks')">
              <IconGlyph name="task" />
            </button>
            <button type="button" class="icon-button" title="区域与虚拟墙" @click="openDialog('assets')">
              <IconGlyph name="layers" />
            </button>
            <button type="button" class="icon-button" title="绘制虚拟墙" @click="beginWallDrawing">
              <IconGlyph name="wall" />
            </button>
            <button type="button" class="icon-button" title="自定义节点路径" @click="beginWaypointMode">
              <IconGlyph name="route" />
            </button>
            <button
              type="button"
              class="icon-button"
              :title="mappingReady ? '地图已就绪' : '一键全屋扫描'"
              :disabled="snapshot.world.mapping.status === 'scanning'"
              @click="startWholeHomeScan()"
            >
              <IconGlyph name="scan" />
            </button>
          </div>
        </div>

        <div class="stage__cluster stage__cluster--status">
          <span class="stage__section-label">任务</span>
          <div class="stage__hud stage__hud--status">
            <article class="compact-stat" :title="activeTask?.title ?? '暂无任务'">
              <div class="compact-stat__icon">
                <IconGlyph name="task" />
              </div>
              <strong>{{ compactTaskLabel }}</strong>
            </article>
            <article class="compact-stat" :title="destinationSummary">
              <div class="compact-stat__icon">
                <IconGlyph name="target" />
              </div>
              <strong>{{ compactDestinationLabel }}</strong>
            </article>
            <article class="compact-stat" :title="`实时延迟 ${Math.round(snapshot.runtime.telemetry.networkRttMs)} ms`">
              <div class="compact-stat__icon">
                <IconGlyph name="timer" />
              </div>
              <strong>{{ Math.round(snapshot.runtime.telemetry.networkRttMs) }}ms</strong>
            </article>
          </div>
        </div>

        <div class="stage__cluster stage__cluster--robot">
          <span class="stage__section-label">设备</span>
          <div class="stage__hud stage__hud--robot">
            <article class="compact-stat" :title="`CPU ${Math.round(snapshot.runtime.telemetry.cpuPercent)}%`">
              <div class="compact-stat__icon">
                <IconGlyph name="cpu" />
              </div>
              <strong>{{ Math.round(snapshot.runtime.telemetry.cpuPercent) }}%</strong>
            </article>
            <article class="compact-stat" :title="`温度 ${snapshot.runtime.telemetry.temperatureC.toFixed(1)}℃`">
              <div class="compact-stat__icon">
                <IconGlyph name="thermo" />
              </div>
              <strong>{{ snapshot.runtime.telemetry.temperatureC.toFixed(1) }}℃</strong>
            </article>
            <article class="compact-stat" :title="`速度 ${snapshot.runtime.robotPose.linearVelocity.toFixed(2)} m/s`">
              <div class="compact-stat__icon">
                <IconGlyph name="speed" />
              </div>
              <strong>{{ snapshot.runtime.robotPose.linearVelocity.toFixed(2) }}</strong>
            </article>
            <article class="compact-stat" :title="`电机电流 ${snapshot.runtime.telemetry.motorCurrentA.toFixed(1)} A`">
              <div class="compact-stat__icon">
                <IconGlyph name="current" />
              </div>
              <strong>{{ snapshot.runtime.telemetry.motorCurrentA.toFixed(1) }}A</strong>
            </article>
          </div>
        </div>

        <div class="stage__panel stage__panel--camera">
          <div class="camera-card__head">
            <strong>{{ snapshot.runtime.camera.title }}</strong>
            <span>{{ snapshot.runtime.camera.connected ? '在线' : '离线' }}</span>
          </div>
          <img :src="snapshot.runtime.camera.frameUrl" :alt="snapshot.runtime.camera.title" />
          <div class="camera-card__meta">
            <span>{{ snapshot.runtime.camera.fps }} FPS</span>
            <span>{{ snapshot.runtime.camera.latencyMs }} ms</span>
          </div>
        </div>

        <div class="control-dock">
          <button
            type="button"
            class="control-button"
            :title="hasPlannedPath ? '执行规划路径' : '开始巡检'"
            @click="hasPlannedPath ? executePlannedPath() : startPatrol()"
          >
            <IconGlyph name="play" />
            <span>{{ hasPlannedPath ? '执行' : '巡检' }}</span>
          </button>
          <button type="button" class="control-button" title="暂停" @click="pauseMission">
            <IconGlyph name="pause" />
            <span>暂停</span>
          </button>
          <button type="button" class="control-button" title="返航回桩" @click="returnHome">
            <IconGlyph name="home" />
            <span>返航</span>
          </button>
          <button type="button" class="control-button" title="清理告警" @click="clearAlerts">
            <IconGlyph name="clear" />
            <span>清告警</span>
          </button>
          <button type="button" class="control-button" title="语音通道" @click="toggleVoice">
            <IconGlyph name="mic" />
            <span>{{ snapshot.runtime.voice.listening ? '收音中' : '语音' }}</span>
          </button>
        </div>

        <button
          v-if="chatCollapsed"
          type="button"
          class="chat-fab"
          title="展开对话历史"
          @click="openChatPanel"
        >
          <IconGlyph name="chat" />
          <span class="chat-fab__badge">{{ Math.min(chatMessageCount, 99) }}</span>
        </button>

        <section v-else class="chat-panel">
          <header class="chat-panel__header">
            <div class="chat-panel__title">
              <IconGlyph name="chat" />
              <div>
                <strong>小车对话历史</strong>
                <span>{{ snapshot.runtime.voice.transcript }}</span>
              </div>
            </div>
            <div class="chat-panel__actions">
              <button
                type="button"
                class="chat-panel__icon-action chat-panel__icon-action--ghost"
                title="收起"
                @click="closeChatPanel"
              >
                <IconGlyph name="collapse" />
              </button>
              <button type="button" class="chat-panel__icon-action" title="任务" @click="openDialog('tasks')">
                <IconGlyph name="task" />
              </button>
            </div>
          </header>

          <div class="chat-panel__body">
            <article
              v-for="message in visibleMessages"
              :key="message.id"
              class="message"
              :class="`message--${message.role}`"
            >
              <header>
                <strong>{{ message.role === 'user' ? '我' : message.role === 'assistant' ? '小车 AI' : '系统' }}</strong>
                <time>{{ message.timestamp }}</time>
              </header>
              <p>{{ message.content }}</p>
            </article>
          </div>

          <form class="chat-compose" @submit.prevent="submitAiCommand">
            <input v-model="aiCommand" type="text" placeholder="输入 AI 指令，或直接在地图上右键导航" />
            <button type="submit" class="chat-compose__send">
              <IconGlyph name="send" />
            </button>
          </form>
        </section>

        <div v-if="!mappingReady" class="stage__empty">
          <div class="empty-state">
            <div class="empty-state__icon">
              <IconGlyph name="scan" />
            </div>
            <h3>{{ snapshot.world.mapping.status === 'scanning' ? '全屋自动避障扫描中' : '工作区尚未建模' }}</h3>
            <p>{{ snapshot.world.mapping.hint }}</p>
            <div class="progress-bar">
              <div class="progress-bar__fill" :style="{ width: `${snapshot.world.mapping.progressPct}%` }" />
            </div>
            <button
              type="button"
              class="empty-state__action"
              :disabled="snapshot.world.mapping.status === 'scanning'"
              @click="startWholeHomeScan()"
            >
              {{ snapshot.world.mapping.status === 'scanning' ? `扫描中 ${snapshot.world.mapping.progressPct}%` : '一键全屋扫描' }}
            </button>
          </div>
        </div>
      </section>
    </main>

    <div v-if="activeDialog" class="dialog-backdrop" @click.self="closeDialog">
      <section v-if="activeDialog === 'tasks'" class="dialog">
        <header class="dialog__header">
          <div>
            <h3>任务队列</h3>
            <p>查看当前巡检、导航、建图与 AI 任务状态。</p>
          </div>
          <button type="button" class="dialog__close" @click="closeDialog">关闭</button>
        </header>

        <div class="task-list">
          <article v-for="task in snapshot.runtime.tasks" :key="task.id" class="task-card">
            <div class="task-card__main">
              <strong>{{ task.title }}</strong>
              <span>{{ taskStatusLabels[task.status] }}</span>
            </div>
            <div class="task-card__meta">
              <span>{{ task.progressPct }}%</span>
              <span>{{ task.etaSec }} s</span>
            </div>
          </article>
        </div>
      </section>

      <section v-else class="dialog dialog--wide">
        <header class="dialog__header">
          <div>
            <h3>区域标签与虚拟墙</h3>
            <p>可新增、修改、删除区域标签，也可在地图上直接绘制虚拟墙。</p>
          </div>
          <button type="button" class="dialog__close" @click="closeDialog">关闭</button>
        </header>

        <div class="dialog__content">
          <section class="dialog-block">
            <div class="dialog-block__head">
              <strong>区域标签</strong>
              <button type="button" class="mini-action" @click="addRegionLabel">
                <IconGlyph name="plus" />
                <span>新增</span>
              </button>
            </div>

            <div class="dialog-form">
              <input v-model="newLabelName" type="text" placeholder="输入区域标签名称" />
            </div>

            <div class="editable-list">
              <article v-for="label in snapshot.world.regionLabels" :key="label.id" class="editable-row">
                <input :value="label.name" type="text" @input="renameRegionLabel(label.id, $event)" />
                <button type="button" class="ghost-icon" title="重新放置" @click="beginLabelPlacement(label.id)">
                  <IconGlyph name="target" />
                </button>
                <button type="button" class="ghost-icon" @click="removeRegionLabel(label.id)">
                  <IconGlyph name="trash" />
                </button>
              </article>
            </div>
          </section>

          <section class="dialog-block">
            <div class="dialog-block__head">
              <strong>虚拟墙</strong>
              <button type="button" class="mini-action" @click="beginWallDrawing">
                <IconGlyph name="wall" />
                <span>地图绘制</span>
              </button>
            </div>

            <div class="editable-list">
              <article v-for="wall in snapshot.world.virtualWalls" :key="wall.id" class="editable-row editable-row--wall">
                <label class="toggle">
                  <input type="checkbox" :checked="wall.enabled" @change="toggleWall(wall.id)" />
                  <span />
                </label>
                <input :value="wall.name" type="text" @change="renameWall(wall.id, $event)" />
                <button type="button" class="ghost-icon" @click="removeWall(wall.id)">
                  <IconGlyph name="trash" />
                </button>
              </article>
            </div>
          </section>
        </div>
      </section>
    </div>
  </div>
</template>
