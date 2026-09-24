<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchRealSnapshot, type RealSnapshot, type Vec2 } from '@/data/realSnapshot'
import { fetchVoiceStatus, unavailableVoiceStatus, voiceStateLabel } from '@/lib/voiceClient'
import { RoverScene } from '@/lib/roverScene'
import type { VoiceStatus } from '@/types/contract'

type ViewMode = '2d' | '3d' | 'video'
interface RadarPoint { angle_rad: number; range_m: number; x_m: number; y_m: number; intensity: number | null }
interface RadarState { available: boolean; frame_id: string; timestamp: string; range_max_m: number; points: RadarPoint[]; error: string | null }
interface CameraState { available: boolean; device: string; width?: number; height?: number; fps?: number; error?: string | null }
interface GimbalState { available: boolean; pan_deg: number | null; tilt_deg: number | null; error: string | null }
type GimbalAxis = 'pan_deg' | 'tilt_deg'
type GimbalCommand = Partial<Record<GimbalAxis, number>>
interface PlannedPath { waypoints: Array<{ x: number; y: number }>; length_m: number; message: string }
type ZoneKind = 'semantic' | 'keepout' | 'slow' | 'virtual_wall'

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
// Prefer same-origin API calls so a console opened from another device does
// not accidentally target that device's own 127.0.0.1.
const apiBaseUrl = configuredApiBaseUrl.includes('127.0.0.1') && window.location.hostname !== '127.0.0.1'
  ? `http://${window.location.hostname}:8001`
  : configuredApiBaseUrl
const snapshot = ref<RealSnapshot | null>(null)
const voice = ref<VoiceStatus>(unavailableVoiceStatus())
const radar = ref<RadarState>({ available: false, frame_id: 'laser_frame', timestamp: '', range_max_m: 0, points: [], error: '雷达数据不可用' })
const camera = ref<CameraState>({ available: false, device: '/dev/video0', error: '摄像头状态未知' })
const cameraFrameError = ref(false)
const gimbal = ref<GimbalState>({ available: false, pan_deg: null, tilt_deg: null, error: '云台状态未知' })
const viewMode = ref<ViewMode>('2d')
const radarOverlay = ref(true)
const apiState = ref<'loading' | 'online' | 'stale' | 'unavailable'>('loading')
const lastError = ref('')
const lastRefreshAt = ref<string | null>(null)
const chatInput = ref('')
const chatBusy = ref(false)
const chatMessages = ref<Array<{ role: 'user' | 'assistant'; text: string }>>([])
const chatSessionId = ref<string | null>(null)
const pathPlan = ref<PlannedPath | null>(null)
const pathError = ref('')
const gridError = ref('')
const occupancyData = ref<Int8Array | null>(null)
const pathBusy = ref(false)
const mappingBusy = ref(false)
const mappingMessage = ref('')
const zoneBusy = ref(false)
const zoneMessage = ref('')
const drawingZone = ref(false)
const selectingPathGoal = ref(false)
const draftPoints = ref<Vec2[]>([])
const zoneName = ref('')
const zoneKind = ref<ZoneKind>('semantic')
const selectedZoneId = ref<string | null>(null)
const editedZoneName = ref('')
const mapSvg = ref<SVGSVGElement | null>(null)
const pan = ref(0)
const tilt = ref(0)
const sceneHost = ref<HTMLDivElement | null>(null)
let scene: RoverScene | null = null
let refreshTimer: number | null = null
let refreshInFlight = false
let gimbalControlsTouched = false
let gimbalRequestInFlight = false
let gimbalSendTimer: number | null = null
let gimbalLastSentAt = 0
let gimbalPending: GimbalCommand = {}
let sceneHasWorld = false
let gridEtag: string | null = null
let gridVersion: string | null = null

const selectedZone = computed(() => snapshot.value?.zones.find((zone) => zone.id === selectedZoneId.value) ?? null)
const voiceLabel = computed(() => voiceStateLabel(voice.value))
const sensorLabel = computed(() => snapshot.value?.sensor.available ? '在线' : '不可用')
const cameraUrl = computed(() => `${apiBaseUrl}/api/v1/camera/mjpeg`)
const occupancyImage = computed(() => {
  const current = snapshot.value
  if (!current?.mapAvailable || !occupancyData.value) return ''
  const grid = current.occupancy
  if (grid.width < 1 || grid.height < 1) return ''
  const canvas = document.createElement('canvas')
  canvas.width = grid.width
  canvas.height = grid.height
  const context = canvas.getContext('2d')
  if (!context) return ''
  const image = context.createImageData(grid.width, grid.height)
  for (let row = 0; row < grid.height; row += 1) {
    const displayRow = grid.height - row - 1
    for (let column = 0; column < grid.width; column += 1) {
      const occupancy = occupancyData.value[row * grid.width + column]
      const offset = (displayRow * grid.width + column) * 4
      if (occupancy < 0) {
        image.data[offset + 3] = 0
      } else if (occupancy >= 65) {
        image.data[offset] = 210
        image.data[offset + 1] = 227
        image.data[offset + 2] = 217
        image.data[offset + 3] = 255
      } else {
        image.data[offset] = 36
        image.data[offset + 1] = 58
        image.data[offset + 2] = 57
        image.data[offset + 3] = 255
      }
    }
  }
  context.putImageData(image, 0, 0)
  return canvas.toDataURL('image/png')
})

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString()
}

function mapProjection(): { scale: number; offsetX: number; offsetY: number } | null {
  const bounds = snapshot.value?.mapBounds
  if (!bounds) return null
  const width = Math.max(bounds.max[0] - bounds.min[0], 0.001)
  const height = Math.max(bounds.max[1] - bounds.min[1], 0.001)
  const scale = Math.min(1000 / width, 700 / height)
  return { scale, offsetX: (1000 - width * scale) / 2, offsetY: (700 - height * scale) / 2 }
}

function worldToCanvas(point: Vec2): Vec2 {
  const bounds = snapshot.value?.mapBounds
  const projection = mapProjection()
  if (!bounds || !projection) return [0, 0]
  return [
    projection.offsetX + (point[0] - bounds.min[0]) * projection.scale,
    projection.offsetY + (bounds.max[1] - point[1]) * projection.scale,
  ]
}

function canvasToWorld(x: number, y: number): Vec2 {
  const bounds = snapshot.value?.mapBounds
  const projection = mapProjection()
  if (!bounds || !projection) return [0, 0]
  return [
    bounds.min[0] + (x - projection.offsetX) / projection.scale,
    bounds.max[1] - (y - projection.offsetY) / projection.scale,
  ]
}

function projectPoint(point: Vec2): string {
  const [x, y] = worldToCanvas(point)
  return `${x.toFixed(2)},${y.toFixed(2)}`
}

function mapImageTransform(): string {
  const current = snapshot.value
  if (!current) return ''
  const grid = current.occupancy
  const width = grid.width * grid.resolution
  const height = grid.height * grid.resolution
  const cosine = Math.cos(grid.originYaw)
  const sine = Math.sin(grid.originYaw)
  const gridToWorld = (x: number, y: number): Vec2 => [
    grid.origin[0] + cosine * x - sine * y,
    grid.origin[1] + sine * x + cosine * y,
  ]
  const bottomLeft = worldToCanvas(gridToWorld(0, 0))
  const bottomRight = worldToCanvas(gridToWorld(width, 0))
  const topLeft = worldToCanvas(gridToWorld(0, height))
  const values = [
    (bottomRight[0] - bottomLeft[0]) / 1000,
    (bottomRight[1] - bottomLeft[1]) / 1000,
    (bottomLeft[0] - topLeft[0]) / 700,
    (bottomLeft[1] - topLeft[1]) / 700,
    topLeft[0],
    topLeft[1],
  ]
  return `matrix(${values.map((value) => value.toFixed(6)).join(' ')})`
}

function radarPoint(point: RadarPoint): string {
  const pose = snapshot.value?.robotPose
  if (!pose?.available || pose.x === null || pose.y === null || pose.yawRad === null) return '0,0'
  const x = pose.x + Math.cos(pose.yawRad) * point.x_m - Math.sin(pose.yawRad) * point.y_m
  const y = pose.y + Math.sin(pose.yawRad) * point.x_m + Math.cos(pose.yawRad) * point.y_m
  return projectPoint([x, y])
}

function zonePoints(points: Vec2[]): string { return points.map(projectPoint).join(' ') }
function zoneFill(type: string): string {
  if (type === 'keepout') return 'rgba(220, 92, 82, 0.42)'
  if (type === 'virtual_wall') return 'rgba(234, 178, 58, 0.42)'
  if (type === 'slow') return 'rgba(62, 180, 160, 0.36)'
  return 'rgba(91, 138, 190, 0.34)'
}

function selectZone(zoneId: string): void {
  selectedZoneId.value = zoneId
  editedZoneName.value = snapshot.value?.zones.find((zone) => zone.id === zoneId)?.name ?? ''
}

function mapClick(event: MouseEvent): void {
  if ((!drawingZone.value && !selectingPathGoal.value) || !snapshot.value?.mapAvailable || !mapSvg.value) return
  const screenTransform = mapSvg.value.getScreenCTM()
  if (!screenTransform) return
  const screenPoint = mapSvg.value.createSVGPoint()
  screenPoint.x = event.clientX
  screenPoint.y = event.clientY
  const canvasPoint = screenPoint.matrixTransform(screenTransform.inverse())
  const [worldX, worldY] = canvasToWorld(canvasPoint.x, canvasPoint.y)
  if (drawingZone.value) {
    draftPoints.value.push([worldX, worldY])
    return
  }
  if (selectingPathGoal.value) {
    selectingPathGoal.value = false
    void requestPath({ x: worldX, y: worldY })
  }
}

function beginPathSelection(): void {
  drawingZone.value = false
  selectingPathGoal.value = true
  pathError.value = '点击地图上的可通行目标点'
}

async function requestPath(goal?: { x: number; y: number }): Promise<void> {
  if (!snapshot.value?.robotPose.available) {
    pathError.value = snapshot.value?.robotPose.error || '当前没有 map 坐标系下的机器人位姿'
    return
  }
  pathBusy.value = true
  pathError.value = ''
  try {
    const body = goal ? { goal } : selectedZoneId.value ? { zone_id: selectedZoneId.value } : null
    if (!body) throw new Error('请先选择区域或点击地图设置目标点')
    const response = await fetch(`${apiBaseUrl}/api/v1/navigation/plan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    const result = await response.json() as PlannedPath & { detail?: string }
    if (!response.ok) throw new Error(result.detail || `路径规划失败 (${response.status})`)
    pathPlan.value = result
    updateScene()
  } catch (error) {
    pathPlan.value = null
    pathError.value = error instanceof Error ? error.message : '路径规划失败'
  } finally {
    pathBusy.value = false
  }
}

async function planNextFrontier(): Promise<void> {
  pathBusy.value = true
  pathError.value = ''
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/navigation/exploration/next`, { method: 'POST' })
    const result = await response.json() as PlannedPath & { detail?: string }
    if (!response.ok) throw new Error(result.detail || `前沿规划失败 (${response.status})`)
    pathPlan.value = result
    updateScene()
  } catch (error) {
    pathPlan.value = null
    pathError.value = error instanceof Error ? error.message : '前沿规划失败'
  } finally {
    pathBusy.value = false
  }
}

async function mappingCommand(action: 'start' | 'pause' | 'resume' | 'stop' | 'save'): Promise<void> {
  mappingBusy.value = true
  mappingMessage.value = ''
  try {
    const explorationState = snapshot.value?.mission.explorationState ?? 'idle'
    const autoSession = explorationState !== 'idle'
    const url = action === 'start'
      ? `${apiBaseUrl}/api/v1/missions/exploration/start`
      : action !== 'save' && autoSession
        ? `${apiBaseUrl}/api/v1/missions/exploration/${action}`
        : `${apiBaseUrl}/api/v1/mapping/${action}`
    const payload = action === 'start'
      ? { session_id: `map-${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}` }
      : action === 'save' ? { map_name: `map-${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}` } : undefined
    const response = await fetch(url, { method: 'POST', ...(payload ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {}) })
    const result = await response.json() as { message?: string; detail?: string }
    if (!response.ok) throw new Error(result.detail || `建图命令失败 (${response.status})`)
    mappingMessage.value = result.message || '命令已执行'
    await refresh()
  } catch (error) {
    mappingMessage.value = error instanceof Error ? error.message : '建图命令失败'
  } finally {
    mappingBusy.value = false
  }
}

function beginZoneDrawing(): void {
  if (!snapshot.value?.mapAvailable) return
  drawingZone.value = true
  draftPoints.value = []
  zoneMessage.value = '点击地图依次添加顶点'
}

function cancelZoneDrawing(): void {
  drawingZone.value = false
  draftPoints.value = []
  zoneMessage.value = ''
}

async function saveZone(): Promise<void> {
  if (!zoneName.value.trim() || draftPoints.value.length < (zoneKind.value === 'virtual_wall' ? 2 : 3)) {
    zoneMessage.value = zoneKind.value === 'virtual_wall' ? '请填写名称并添加至少 2 个端点' : '请填写名称并添加至少 3 个区域顶点'
    return
  }
  zoneBusy.value = true
  try {
    const id = `zone-${Date.now().toString(36)}`
    const response = await fetch(`${apiBaseUrl}/api/v1/zones`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        zone_id: id, name: zoneName.value.trim(), type: zoneKind.value,
        points: draftPoints.value.map(([x, y]) => ({ x, y })),
        nav2_keepout_enabled: zoneKind.value === 'keepout',
        nav2_virtual_wall_enabled: zoneKind.value === 'virtual_wall',
        semantic_label: zoneKind.value === 'semantic' ? zoneName.value.trim() : null,
      }),
    })
    const result = await response.json() as { detail?: string }
    if (!response.ok) throw new Error(result.detail || `区域保存失败 (${response.status})`)
    zoneName.value = ''
    cancelZoneDrawing()
    zoneMessage.value = '区域标签已保存'
    await refresh()
    selectZone(id)
  } catch (error) {
    zoneMessage.value = error instanceof Error ? error.message : '区域保存失败'
  } finally {
    zoneBusy.value = false
  }
}

async function updateZone(): Promise<void> {
  if (!selectedZone.value || !editedZoneName.value.trim()) return
  zoneBusy.value = true
  try {
    const zone = selectedZone.value
    const response = await fetch(`${apiBaseUrl}/api/v1/zones/${encodeURIComponent(zone.id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        zone_id: zone.id, name: editedZoneName.value.trim(), type: zone.type,
        points: zone.points.map(([x, y]) => ({ x, y })),
        nav2_keepout_enabled: zone.keepoutEnabled,
        nav2_virtual_wall_enabled: zone.virtualWallEnabled,
        semantic_label: zone.semanticLabel,
      }),
    })
    const result = await response.json() as { detail?: string }
    if (!response.ok) throw new Error(result.detail || `区域更新失败 (${response.status})`)
    zoneMessage.value = '区域标签已更新'
    await refresh()
  } catch (error) {
    zoneMessage.value = error instanceof Error ? error.message : '区域更新失败'
  } finally {
    zoneBusy.value = false
  }
}

async function deleteZone(): Promise<void> {
  if (!selectedZone.value) return
  zoneBusy.value = true
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/zones/${encodeURIComponent(selectedZone.value.id)}`, { method: 'DELETE' })
    const result = await response.json() as { detail?: string }
    if (!response.ok) throw new Error(result.detail || `区域删除失败 (${response.status})`)
    selectedZoneId.value = null
    zoneMessage.value = '区域标签已删除'
    await refresh()
  } catch (error) {
    zoneMessage.value = error instanceof Error ? error.message : '区域删除失败'
  } finally {
    zoneBusy.value = false
  }
}

function sceneWorld() {
  if (!snapshot.value) return null
  return {
    mapId: snapshot.value.mapId,
    mapName: snapshot.value.mapName,
    bounds: snapshot.value.mapBounds,
    zones: snapshot.value.zones.map((zone) => ({
      id: zone.id,
      name: zone.name,
      category: (zone.type === 'keepout' ? 'restricted' : zone.type === 'slow' ? 'lane' : 'room') as 'restricted' | 'lane' | 'room',
      polygon: zone.points,
      selectable: true,
    })),
    virtualWalls: snapshot.value.walls.map((wall) => ({ id: wall.id, name: wall.name, start: wall.points[0] ?? [0, 0], end: wall.points[1] ?? [0, 0], height: 0.8, enabled: wall.enabled })),
    occupancy: {
      width: snapshot.value.occupancy.width,
      height: snapshot.value.occupancy.height,
      resolution: snapshot.value.occupancy.resolution,
      origin: snapshot.value.occupancy.origin,
      originYaw: snapshot.value.occupancy.originYaw,
      data: occupancyData.value,
    },
  }
}

function updateScene(): void {
  if (!sceneHost.value || !snapshot.value?.mapAvailable || !occupancyData.value || viewMode.value !== '3d') return
  if (!scene) scene = new RoverScene(sceneHost.value)
  const world = sceneWorld()
  if (!world) return
  scene.setWorld(world, !sceneHasWorld)
  sceneHasWorld = true
  scene.setRuntime({
    selectedZoneId: selectedZoneId.value,
    poseAvailable: snapshot.value.robotPose.available,
    robotPose: { x: snapshot.value.robotPose.x ?? 0, y: snapshot.value.robotPose.y ?? 0, yawRad: snapshot.value.robotPose.yawRad ?? 0, linearVelocity: snapshot.value.robotPose.linearVelocityMps ?? 0, angularVelocity: snapshot.value.robotPose.angularVelocityRadps ?? 0, frameId: 'map', stampMs: Date.now() },
    path: { id: 'planned-preview', status: pathPlan.value ? 'planned' : 'idle', waypoints: pathPlan.value?.waypoints.map((point) => [point.x, point.y] as Vec2) ?? [] },
    lidar: { frameId: radar.value.frame_id, stampMs: Date.now(), maxRangeM: radar.value.range_max_m, points: radar.value.points.map((point) => ({ x: point.x_m, y: point.y_m, intensity: point.intensity ?? 0.5 })) },
    camera: { sourceId: 'camera', title: 'V4L2', connected: camera.value.available, frameUrl: cameraUrl.value, width: camera.value.width ?? 0, height: camera.value.height ?? 0, fps: camera.value.fps ?? 0, latencyMs: 0 },
    telemetry: { batteryPercent: snapshot.value.sensor.batteryPercent ?? 0, cpuPercent: 0, temperatureC: snapshot.value.sensor.boardTemperatureC ?? 0, networkRttMs: 0, localizationConfidence: 0, motorCurrentA: 0 },
    mission: { mode: snapshot.value.mission.mode === 'autonomy' ? 'autonomy' : 'idle', objective: snapshot.value.mission.objective, statusLine: snapshot.value.mission.statusLine },
    tasks: snapshot.value.tasks.map((task) => ({ id: task.id, title: task.description, status: task.status === 'completed' ? 'done' : task.status === 'running' ? 'running' : 'queued', progressPct: 0, etaSec: 0 })),
    voice: { listening: false, wakeWordArmed: voice.value.enabled, transcript: '', confidence: 0 },
  })
}

async function refresh(): Promise<void> {
  if (refreshInFlight) return
  refreshInFlight = true
  try {
    const responses = await Promise.allSettled([
      fetchRealSnapshot(apiBaseUrl),
      fetchVoiceStatus(apiBaseUrl),
      fetch(`${apiBaseUrl}/api/v1/radar`).then(async (response) => { if (!response.ok) throw new Error(`雷达请求失败 (${response.status})`); return await response.json() as RadarState }),
      fetch(`${apiBaseUrl}/api/v1/camera/status`).then(async (response) => { if (!response.ok) throw new Error(`摄像头请求失败 (${response.status})`); return await response.json() as CameraState }),
      fetch(`${apiBaseUrl}/api/v1/gimbal`).then(async (response) => { if (!response.ok) throw new Error(`云台请求失败 (${response.status})`); return await response.json() as GimbalState }),
    ])
    if (responses[0].status === 'fulfilled') {
      snapshot.value = responses[0].value
      apiState.value = 'online'
      lastError.value = ''
      await refreshOccupancyGrid(responses[0].value)
    }
    else { apiState.value = snapshot.value ? 'stale' : 'unavailable'; lastError.value = responses[0].reason instanceof Error ? responses[0].reason.message : '真实地图数据不可用' }
    if (responses[1].status === 'fulfilled') voice.value = responses[1].value
    if (responses[2].status === 'fulfilled') radar.value = responses[2].value
    if (responses[3].status === 'fulfilled') { camera.value = responses[3].value; cameraFrameError.value = false }
    if (responses[4].status === 'fulfilled') {
      gimbal.value = responses[4].value
      // The hardware has no position feedback; these values are only the last
      // command and must not overwrite a value the operator is currently setting.
      if (!gimbalControlsTouched) {
        if (responses[4].value.pan_deg !== null) pan.value = responses[4].value.pan_deg
        if (responses[4].value.tilt_deg !== null) tilt.value = responses[4].value.tilt_deg
      }
    }
    lastRefreshAt.value = new Date().toISOString()
    updateScene()
  } finally {
    refreshInFlight = false
  }
}

async function refreshOccupancyGrid(current: RealSnapshot): Promise<void> {
  if (!current.mapAvailable) {
    occupancyData.value = null
    gridVersion = null
    gridEtag = null
    gridError.value = ''
    return
  }
  if (gridVersion === current.mapUpdatedAt && occupancyData.value) return
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/map/grid`, {
      headers: gridEtag ? { 'If-None-Match': gridEtag } : {},
    })
    if (response.status === 304) {
      gridVersion = current.mapUpdatedAt
      return
    }
    if (!response.ok) throw new Error(`地图栅格请求失败 (${response.status})`)
    const compressed = await response.arrayBuffer()
    if (typeof DecompressionStream === 'undefined') throw new Error('当前浏览器不支持地图流解压')
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate'))
    const bytes = new Uint8Array(await new Response(stream).arrayBuffer())
    if (bytes.length !== current.occupancy.width * current.occupancy.height) throw new Error('地图栅格尺寸与元数据不匹配')
    occupancyData.value = new Int8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    gridEtag = response.headers.get('ETag')
    gridVersion = current.mapUpdatedAt
    gridError.value = ''
  } catch (error) {
    occupancyData.value = null
    gridVersion = null
    gridError.value = error instanceof Error ? error.message : '地图栅格不可用'
  }
}

function apiStateLabel(): string { return { loading: '连接中', online: '真实数据在线', stale: '数据已过期', unavailable: '数据不可用' }[apiState.value] }

function scheduleGimbalSend(immediate = false): void {
  if (gimbalSendTimer !== null) window.clearTimeout(gimbalSendTimer)
  const waitMs = immediate ? 0 : Math.max(0, 50 - (Date.now() - gimbalLastSentAt))
  gimbalSendTimer = window.setTimeout(() => {
    gimbalSendTimer = null
    void flushGimbalCommands()
  }, waitMs)
}

function queueGimbalCommand(axis: GimbalAxis, value: number, flush = false): void {
  gimbalControlsTouched = true
  gimbalPending = { ...gimbalPending, [axis]: value }
  scheduleGimbalSend(flush)
}

async function flushGimbalCommands(): Promise<void> {
  if (gimbalRequestInFlight) return
  const command = gimbalPending
  if (Object.keys(command).length === 0) return
  gimbalPending = {}
  gimbalRequestInFlight = true
  gimbalLastSentAt = Date.now()
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/gimbal`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) })
    if (!response.ok) throw new Error(`云台命令失败 (${response.status})`)
    gimbal.value = await response.json() as GimbalState
  } catch (error) {
    gimbal.value = { ...gimbal.value, available: false, error: error instanceof Error ? error.message : '云台命令失败' }
  } finally {
    gimbalRequestInFlight = false
    if (Object.keys(gimbalPending).length > 0 && gimbalSendTimer === null) {
      scheduleGimbalSend()
    }
  }
}

async function sendChat(): Promise<void> {
  const text = chatInput.value.trim()
  if (!text || chatBusy.value) return
  chatMessages.value.push({ role: 'user', text })
  chatInput.value = ''
  chatBusy.value = true
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/assistant/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ transcript: text, ...(chatSessionId.value ? { session_id: chatSessionId.value } : {}) }) })
    if (!response.ok) throw new Error(`助手不可用 (${response.status})`)
    const result = await response.json() as { session_id: string; reply_text: string }
    chatSessionId.value = result.session_id
    chatMessages.value.push({ role: 'assistant', text: result.reply_text })
  } catch (error) {
    chatMessages.value.push({ role: 'assistant', text: error instanceof Error ? error.message : '助手不可用' })
  } finally { chatBusy.value = false }
}

watch(viewMode, () => {
  if (viewMode.value !== '3d' && scene) {
    scene.destroy()
    scene = null
    sceneHasWorld = false
  }
  window.setTimeout(updateScene, 0)
})
onMounted(() => { void refresh(); refreshTimer = window.setInterval(() => void refresh(), 3000) })
onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  if (gimbalSendTimer !== null) window.clearTimeout(gimbalSendTimer)
  scene?.destroy()
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">J</span><div><div class="eyebrow">JARVIS ROVER / ROS2 HUMBLE</div><h1>小车控制台</h1></div></div>
      <div class="top-status"><span class="status-dot" :class="`status-dot--${apiState}`" />{{ apiStateLabel() }}<span class="divider" />地图：{{ snapshot?.mapAvailable ? snapshot.mapName : '未生成' }}<span class="divider" />建图：{{ snapshot?.mapping.state ?? '未知' }}<span class="divider" />刷新：{{ formatTime(lastRefreshAt) }}</div>
    </header>
    <main class="workspace">
      <section class="main-column">
        <div class="workspace-head">
          <div><div class="eyebrow">空间工作区</div><h2>{{ snapshot?.mission.statusLine ?? '等待真实运行时数据' }}</h2><p>{{ snapshot?.mission.objective ?? (lastError || '等待 API 与真实 ROS 数据。') }}</p></div>
          <div class="head-metrics"><span>地图源 <b>{{ snapshot?.mapSource ?? '—' }}</b></span><span>区域 <b>{{ snapshot?.zones.length ?? '0' }}</b></span><span>雷达 <b>{{ radar.available ? radar.points.length : '—' }}</b></span><span>位姿 <b>{{ snapshot?.robotPose.available ? '在线' : '不可用' }}</b></span></div>
        </div>
        <div class="view-tabs" role="tablist"><button :class="{ active: viewMode === '2d' }" @click="viewMode = '2d'">2D 地图</button><button :class="{ active: viewMode === '3d' }" @click="viewMode = '3d'">3D 重建</button><button :class="{ active: viewMode === 'video' }" @click="viewMode = 'video'">视频</button><label class="toggle"><input v-model="radarOverlay" type="checkbox" />雷达叠加</label></div>
        <div class="map-actions">
          <button v-if="snapshot?.mapping.state === 'idle'" class="action-button" :disabled="mappingBusy || !snapshot?.mapping.ready" @click="mappingCommand('start')">{{ mappingBusy ? '处理中…' : '开始建图' }}</button>
          <span v-if="snapshot?.mapping.state === 'idle'" class="muted">点击后小车将自主移动探索；启动前会检查 Nav2 与安全门控</span>
          <template v-else-if="snapshot?.mapping.state === 'starting'"><span class="muted">{{ snapshot.mission.explorationState === 'starting' ? 'SLAM / Nav2 启动中，完成安全预检后开始探索' : 'SLAM 启动中，等待首张地图' }}</span><button class="action-button danger" :disabled="mappingBusy" @click="mappingCommand('stop')">取消启动</button></template>
          <template v-else-if="snapshot?.mapping.state === 'mapping'"><button class="action-button" :disabled="mappingBusy" @click="mappingCommand('pause')">{{ snapshot?.mission.explorationState === 'exploring' || snapshot?.mission.explorationState === 'starting' ? '暂停探索' : '暂停建图' }}</button><button class="action-button secondary" :disabled="mappingBusy" @click="mappingCommand('save')">保存地图</button><button class="action-button danger" :disabled="mappingBusy" @click="mappingCommand('stop')">{{ snapshot?.mission.explorationState !== 'idle' ? '停止探索并保存' : '停止并保存' }}</button></template>
          <template v-else-if="snapshot?.mapping.state === 'paused'"><button class="action-button" :disabled="mappingBusy || !snapshot?.mapping.ready" @click="mappingCommand('resume')">{{ snapshot?.mission.explorationState === 'paused' ? '恢复探索' : '恢复建图' }}</button><button class="action-button secondary" :disabled="mappingBusy" @click="mappingCommand('save')">保存地图</button><button class="action-button danger" :disabled="mappingBusy" @click="mappingCommand('stop')">停止并保存</button></template>
          <template v-else-if="snapshot?.mapping.state === 'error_recoverable'"><span class="error-text">{{ snapshot.mapping.lastError || '建图进程已停止' }}</span><button class="action-button secondary" :disabled="mappingBusy" @click="mappingCommand('stop')">清理状态</button></template>
          <span class="muted">{{ mappingMessage || (snapshot?.mapping.ready ? '雷达与里程计在线' : snapshot?.mapping.lastError || '等待雷达与里程计') }}</span>
          <small v-if="snapshot && snapshot.mission.explorationState !== 'idle'" class="muted">探索：{{ snapshot.mission.explorationMessage }} · 已到达 {{ snapshot.mission.completedFrontiers }} · 不可达 {{ snapshot.mission.failedFrontiers }} · 候选 {{ snapshot.mission.remainingFrontiers }}<template v-if="snapshot.mission.currentTarget"> · 目标 ({{ snapshot.mission.currentTarget[0].toFixed(2) }}, {{ snapshot.mission.currentTarget[1].toFixed(2) }})</template></small>
        </div>
        <div class="viewport">
          <svg v-if="viewMode === '2d' && snapshot?.mapAvailable && occupancyData" ref="mapSvg" class="map-canvas" :class="{ drawing: drawingZone || selectingPathGoal }" viewBox="0 0 1000 700" role="img" aria-label="ROS OccupancyGrid 二维地图" @click="mapClick">
            <rect width="1000" height="700" fill="#10191d" />
            <image v-if="occupancyImage" x="0" y="0" width="1000" height="700" preserveAspectRatio="none" :transform="mapImageTransform()" :href="occupancyImage" />
            <g v-for="zone in snapshot.zones" :key="zone.id" @click.stop="selectZone(zone.id)">
              <polygon :points="zonePoints(zone.points)" :fill="zoneFill(zone.type)" :stroke="zone.id === selectedZoneId ? '#f2c75c' : '#77cfc1'" :stroke-width="zone.id === selectedZoneId ? 4 : 2" />
              <text v-if="zone.points[0]" :x="projectPoint(zone.points[0]).split(',')[0]" :y="Number(projectPoint(zone.points[0]).split(',')[1]) - 8" fill="#eaf7f4" font-size="16">{{ zone.name }}</text>
            </g>
            <polyline v-if="draftPoints.length > 1" class="draft-zone" :points="draftPoints.map(projectPoint).join(' ')" />
            <circle v-for="(point, index) in draftPoints" :key="`draft-${index}`" :cx="projectPoint(point).split(',')[0]" :cy="projectPoint(point).split(',')[1]" r="5" fill="#79e1d0" />
            <polyline v-if="pathPlan" class="planned-path" :points="pathPlan.waypoints.map((point) => projectPoint([point.x, point.y])).join(' ')" />
            <g v-if="snapshot.robotPose.available && snapshot.robotPose.x !== null && snapshot.robotPose.y !== null" :transform="`translate(${projectPoint([snapshot.robotPose.x, snapshot.robotPose.y])}) rotate(${-((snapshot.robotPose.yawRad ?? 0) * 180 / Math.PI)})`">
              <path d="M 12 0 L -8 -7 L -8 7 Z" fill="#78ecd7" stroke="#102326" stroke-width="2" />
            </g>
            <g v-if="radarOverlay && radar.available && snapshot.robotPose.available" class="radar-points"><circle v-for="(point, index) in radar.points" :key="index" :cx="radarPoint(point).split(',')[0]" :cy="radarPoint(point).split(',')[1]" r="2.4" fill="#f1d271" /></g>
            <text x="24" y="40" fill="#d2e3df" font-size="14">{{ snapshot.mapId }} · {{ snapshot.mapSource }} · {{ snapshot.occupancy.width }}×{{ snapshot.occupancy.height }} @ {{ snapshot.occupancy.resolution }} m/cell</text>
          </svg>
          <div v-else-if="viewMode === '3d' && snapshot?.mapAvailable && occupancyData" ref="sceneHost" class="scene-host" />
          <div v-else-if="(viewMode === '2d' || viewMode === '3d') && snapshot?.mapAvailable" class="unavailable"><span class="unavailable-icon">!</span><strong>{{ gridError ? '真实地图栅格不可用' : '正在同步真实地图栅格' }}</strong><small>{{ gridError || '正在读取 ROS OccupancyGrid…' }}</small></div>
          <div v-else-if="viewMode === 'video' && camera.available && !cameraFrameError" class="video-wrap"><img :src="cameraUrl" alt="实时摄像头画面" @error="cameraFrameError = true" /><span class="video-badge">{{ camera.width }}×{{ camera.height }} · {{ camera.fps }} fps</span></div>
          <div v-else class="unavailable"><span class="unavailable-icon">!</span><strong>{{ viewMode === 'video' ? '摄像头视频流不可用' : '真实地图数据不可用' }}</strong><small>{{ viewMode === 'video' ? (camera.error || 'MJPEG 视频流连接失败') : (snapshot?.robotPose.error || snapshot?.mapping.lastError || lastError || '请启动 SLAM 建图以生成真实 OccupancyGrid。') }}</small></div>
          <div class="viewport-legend"><span><i class="legend-dot legend-dot--map" />ROS 2D 占据栅格</span><span><i class="legend-dot legend-dot--radar" />雷达点</span><span><i class="legend-dot legend-dot--derived" />3D 由 2D 推导</span></div>
        </div>
        <section class="panel map-tools">
          <div class="panel-title"><span>路径规划与区域标签</span><span class="muted">规划仅生成路径预览，不会驱动底盘</span></div>
          <div class="tool-row"><button class="action-button" :disabled="!snapshot?.mapAvailable || !snapshot?.robotPose.available || pathBusy" @click="requestPath()">规划到所选区域</button><button class="action-button secondary" :disabled="!snapshot?.mapAvailable || !snapshot?.robotPose.available || pathBusy" @click="beginPathSelection">点击地图选目标</button><button class="action-button secondary" :disabled="!snapshot?.mapAvailable || !snapshot?.robotPose.available || pathBusy" @click="planNextFrontier">规划下一个探索前沿</button><button v-if="pathPlan" class="action-button danger" @click="pathPlan = null; pathError = ''">清除路径</button></div>
          <small v-if="pathPlan" class="muted">路径 {{ pathPlan.length_m.toFixed(2) }} m · {{ pathPlan.waypoints.length }} 个路点 · {{ pathPlan.message }}</small><small v-if="pathError" class="error-text">{{ pathError }}</small>
          <div class="tool-row"><button class="action-button" :disabled="!snapshot?.mapAvailable || drawingZone" @click="beginZoneDrawing">新建区域标签</button><select v-model="zoneKind" aria-label="区域类型"><option value="semantic">语义区域</option><option value="keepout">禁行区</option><option value="slow">慢行区</option><option value="virtual_wall">虚拟墙</option></select><input v-model="zoneName" aria-label="区域名称" placeholder="区域名称" maxlength="64" /><button v-if="drawingZone" class="action-button" :disabled="zoneBusy" @click="saveZone">保存标签</button><button v-if="drawingZone" class="action-button secondary" @click="cancelZoneDrawing">取消</button></div>
          <small v-if="drawingZone" class="muted">{{ zoneKind === 'virtual_wall' ? '点击地图添加至少 2 个墙端点' : '点击地图依次添加至少 3 个区域顶点' }} · 已添加 {{ draftPoints.length }} 点</small>
          <div v-if="selectedZone" class="tool-row"><b>已选区域</b><input v-model="editedZoneName" :aria-label="`编辑 ${selectedZone.name} 标签`" maxlength="64" /><button class="action-button" :disabled="zoneBusy" @click="updateZone">更新</button><button class="action-button danger" :disabled="zoneBusy" @click="deleteZone">删除</button></div>
          <small v-if="zoneMessage" class="muted">{{ zoneMessage }}</small>
        </section>
      </section>
      <aside class="sidebar">
        <section class="panel compact"><div class="panel-title"><span>云台</span><span class="availability" :class="{ online: gimbal.available }">{{ gimbal.available ? '控制链路在线' : '不可用' }}</span></div><div class="slider-row"><label>水平 <output>{{ pan }}°</output></label><input v-model.number="pan" type="range" min="-90" max="90" step="1" :disabled="!gimbal.available" @input="queueGimbalCommand('pan_deg', pan)" @change="queueGimbalCommand('pan_deg', pan, true)" /></div><div class="slider-row"><label>俯仰 <output>{{ tilt }}°</output></label><input v-model.number="tilt" type="range" min="-90" max="20" step="1" :disabled="!gimbal.available" @input="queueGimbalCommand('tilt_deg', tilt)" @change="queueGimbalCommand('tilt_deg', tilt, true)" /></div><small class="muted">{{ gimbal.error || '/servo_s1 · /servo_s2 · 设备未提供位置回读' }}</small></section>
        <section class="panel compact"><div class="panel-title"><span>AI 语音对话</span><span class="availability" :class="{ online: voice.enabled && !voice.lastError }">{{ voiceLabel }}</span></div><div class="voice-line"><span class="voice-ring" :class="{ listening: voice.state === 'wake_listening' || voice.state === 'capturing' }" /><div><b>说“贾维斯”唤醒</b><small>{{ voice.enabled ? '可闲聊、问答或查询小车 · 音频不上云' : '本地语音服务未启用 · 音频不上云' }} · 状态 {{ formatTime(voice.receivedAt) }}</small></div></div><div class="chat-log"><div v-for="(message, index) in chatMessages" :key="index" :class="['chat-message', message.role]">{{ message.text }}</div><small v-if="!chatMessages.length" class="muted">输入任意话题测试开放对话；语音由主机服务采集。</small></div><form class="chat-form" @submit.prevent="sendChat"><input v-model="chatInput" placeholder="和贾维斯聊点什么…" maxlength="1000" /><button aria-label="发送">↵</button></form></section>
        <section class="panel compact"><div class="panel-title"><span>传感器与位姿</span><span class="availability" :class="{ online: snapshot?.sensor.available }">{{ sensorLabel }}</span></div><div class="metrics"><div><small>电量</small><b>{{ snapshot?.sensor.batteryPercent ?? '—' }}{{ snapshot?.sensor.batteryPercent === null ? '' : '%' }}</b></div><div><small>雷达点</small><b>{{ radar.available ? radar.points.length : '—' }}</b></div><div><small>IMU 航向</small><b>{{ snapshot?.sensor.yawRad?.toFixed(2) ?? '—' }}</b></div><div><small>地图坐标</small><b>{{ snapshot?.robotPose.available ? `${snapshot.robotPose.x?.toFixed(2)}, ${snapshot.robotPose.y?.toFixed(2)}` : '—' }}</b></div></div><small class="muted">{{ snapshot?.sensor.error || radar.error || snapshot?.robotPose.error || '等待传感器数据' }}</small></section>
        <section class="panel compact"><div class="panel-title"><span>任务与数据源</span><span class="availability" :class="{ online: apiState === 'online' }">{{ apiStateLabel() }}</span></div><div v-if="snapshot?.tasks.length" class="task-list"><div v-for="task in snapshot.tasks" :key="task.id" class="task-row"><b>{{ task.type }}</b><span>{{ task.status }}</span></div></div><small v-else class="muted">暂无活动任务</small><div class="source-list"><div><span class="source-dot" :class="{ online: snapshot }" />API</div><div><span class="source-dot" :class="{ online: radar.available }" />MS200 雷达</div><div><span class="source-dot" :class="{ online: camera.available && !cameraFrameError }" />V4L2 摄像头</div><div><span class="source-dot" :class="{ online: voice.enabled }" />本地语音服务</div><div><span class="source-dot" :class="{ online: snapshot?.mapAvailable }" />SLAM 地图</div></div></section>
      </aside>
    </main>
  </div>
</template>
