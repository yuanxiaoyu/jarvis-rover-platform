import type {
  CameraPanelState,
  ConversationMessage,
  LidarPoint,
  MapBounds,
  MapZone,
  MissionState,
  RegionLabel,
  RoverSnapshot,
  RuntimeState,
  TaskItem,
  Vec2,
  VirtualWall,
  VoiceState,
  WorldModel,
} from '@/types/contract'

const mappedZones: MapZone[] = [
  {
    id: 'dock-west',
    name: '西侧停靠区',
    category: 'dock',
    selectable: true,
    polygon: [
      [0, 0],
      [3.6, 0],
      [3.6, 2.4],
      [0, 2.4],
    ],
    labelAnchor: [1.8, 1.2],
  },
  {
    id: 'atrium-core',
    name: '中庭主区域',
    category: 'room',
    selectable: true,
    polygon: [
      [0, 2.4],
      [8.6, 2.4],
      [8.6, 8.5],
      [0, 8.5],
    ],
    labelAnchor: [4.2, 5.5],
  },
  {
    id: 'service-lane',
    name: '服务通道',
    category: 'lane',
    selectable: true,
    polygon: [
      [3.6, 0],
      [7.4, 0],
      [7.4, 13.2],
      [3.6, 13.2],
    ],
    labelAnchor: [5.5, 6.2],
  },
  {
    id: 'inspection-east',
    name: '东侧巡检区',
    category: 'inspection',
    selectable: true,
    polygon: [
      [8.6, 2.4],
      [16, 2.4],
      [16, 8.5],
      [8.6, 8.5],
    ],
    labelAnchor: [12.4, 5.5],
  },
  {
    id: 'charging-bay',
    name: '充电湾',
    category: 'charging',
    selectable: true,
    polygon: [
      [7.4, 8.5],
      [12.2, 8.5],
      [12.2, 13.2],
      [7.4, 13.2],
    ],
    labelAnchor: [9.8, 10.9],
  },
  {
    id: 'safety-restricted',
    name: '安全限制区',
    category: 'restricted',
    selectable: false,
    polygon: [
      [12.2, 8.5],
      [16, 8.5],
      [16, 13.2],
      [12.2, 13.2],
    ],
    labelAnchor: [14.1, 10.8],
  },
]

const mappedRegionLabels: RegionLabel[] = [
  { id: 'label-dock-west', name: '停靠区', position: [1.8, 1.2], zoneId: 'dock-west' },
  { id: 'label-atrium-core', name: '中庭', position: [4.2, 5.5], zoneId: 'atrium-core' },
  { id: 'label-service-lane', name: '服务主通道', position: [5.5, 3.2], zoneId: 'service-lane' },
  { id: 'label-inspection-east', name: '东侧巡检区', position: [12.4, 5.5], zoneId: 'inspection-east' },
  { id: 'label-charging-bay', name: '充电湾', position: [9.8, 10.9], zoneId: 'charging-bay' },
]

const mappedWalls: VirtualWall[] = [
  {
    id: 'wall-a',
    name: '通道缓冲虚拟墙',
    start: [3.6, 1.2],
    end: [3.6, 3.4],
    height: 1.1,
    enabled: true,
  },
  {
    id: 'wall-b',
    name: '维护围栏',
    start: [10.6, 9.2],
    end: [14.8, 9.2],
    height: 1.3,
    enabled: true,
  },
]

const patrolLoop: Vec2[] = [
  [1.8, 1.2],
  [5.2, 1.2],
  [5.2, 6.1],
  [10.8, 6.1],
  [10.8, 10.6],
  [5.2, 10.6],
  [5.2, 6.1],
  [1.8, 6.1],
]

const emptyBounds: MapBounds = {
  min: [0, 0],
  max: [16, 13.2],
}

const gridResolution = 0.45
const virtualWallMargin = 0.42
const pathProbeStep = 0.18

function cloneVec2([x, y]: Vec2): Vec2 {
  return [x, y]
}

function cloneZone(zone: MapZone): MapZone {
  return {
    ...zone,
    polygon: zone.polygon.map(cloneVec2),
    labelAnchor: zone.labelAnchor ? cloneVec2(zone.labelAnchor) : undefined,
  }
}

function cloneLabel(label: RegionLabel): RegionLabel {
  return {
    ...label,
    position: cloneVec2(label.position),
  }
}

function cloneWall(wall: VirtualWall): VirtualWall {
  return {
    ...wall,
    start: cloneVec2(wall.start),
    end: cloneVec2(wall.end),
  }
}

function formatTimestamp(date = new Date()): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function cameraFrame(label: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="192" viewBox="0 0 320 192">
    <defs>
      <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
        <stop stop-color="#0f1d23" offset="0"/>
        <stop stop-color="#1d3b42" offset="0.45"/>
        <stop stop-color="#0a1419" offset="1"/>
      </linearGradient>
    </defs>
    <rect width="320" height="192" fill="url(#g)"/>
    <rect x="14" y="16" width="292" height="160" rx="12" fill="none" stroke="#8de6d8" stroke-opacity="0.42"/>
    <path d="M18 138 L92 78 L170 108 L228 60 L302 126" fill="none" stroke="#8fe6d6" stroke-width="2.2" stroke-opacity="0.72"/>
    <circle cx="228" cy="60" r="4" fill="#f6d168"/>
    <text x="20" y="182" fill="#d0f8f1" font-size="12" font-family="monospace">${label}</text>
  </svg>`

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

function seedVoice(): VoiceState {
  return {
    listening: false,
    wakeWordArmed: true,
    transcript: '语音待命中，可直接与小车对话。',
    confidence: 0,
  }
}

function seedMission(): MissionState {
  return {
    mode: 'autonomy',
    objective: '验证虚拟墙绘制与路径规划',
    statusLine: '已载入 mock 工作区，可直接绘制隔离墙并验证路径规划。',
  }
}

function seedCamera(): CameraPanelState {
  return {
    sourceId: 'front_cam',
    title: '前置摄像头',
    connected: true,
    frameUrl: cameraFrame('FRONT_CAM / READY'),
    width: 320,
    height: 192,
    fps: 18,
    latencyMs: 112,
  }
}

function seedConversationHistory(): ConversationMessage[] {
  return [
    createConversationMessage('assistant', '欢迎使用贾维斯小车控制台。当前已载入 mock 工作区。'),
    createConversationMessage('assistant', '你可以直接在地图上绘制虚拟墙，并右键验证路径规划。'),
  ]
}

function makeLidar(pose: { x: number; y: number }, tick: number): LidarPoint[] {
  const points: LidarPoint[] = []
  const count = 220

  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2 + tick * 0.06
    const range = 0.8 + 2.8 * Math.abs(Math.sin(i * 0.15 + tick * 0.08))
    const noise = Math.sin(i * 0.77 + tick * 0.19) * 0.08
    points.push({
      x: pose.x + Math.cos(angle) * (range + noise),
      y: pose.y + Math.sin(angle) * (range + noise),
      intensity: 0.42 + 0.58 * Math.abs(Math.sin(i * 0.29 + tick * 0.11)),
    })
  }

  return points
}

function polygonCentroid(points: Vec2[]): Vec2 {
  const total = points.reduce(
    (memo, point) => {
      memo.x += point[0]
      memo.y += point[1]
      return memo
    },
    { x: 0, y: 0 },
  )

  return [total.x / Math.max(points.length, 1), total.y / Math.max(points.length, 1)]
}

function computeBoundsFromZones(zones: MapZone[]): MapBounds {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY

  for (const zone of zones) {
    for (const [x, y] of zone.polygon) {
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }

  if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
    return {
      min: cloneVec2(emptyBounds.min),
      max: cloneVec2(emptyBounds.max),
    }
  }

  return {
    min: [minX, minY],
    max: [maxX, maxY],
  }
}

function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1])
}

function clampPointToBounds(point: Vec2, bounds: MapBounds, margin = 0.28): Vec2 {
  return [
    Math.min(bounds.max[0] - margin, Math.max(bounds.min[0] + margin, point[0])),
    Math.min(bounds.max[1] - margin, Math.max(bounds.min[1] + margin, point[1])),
  ]
}

function pointInPolygon(point: Vec2, polygon: Vec2[]): boolean {
  let inside = false
  const [x, y] = point

  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const xi = polygon[i][0]
    const yi = polygon[i][1]
    const xj = polygon[j][0]
    const yj = polygon[j][1]
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-6) + xi
    if (intersects) {
      inside = !inside
    }
  }

  return inside
}

function distancePointToSegment(point: Vec2, start: Vec2, end: Vec2): number {
  const [px, py] = point
  const [ax, ay] = start
  const [bx, by] = end
  const dx = bx - ax
  const dy = by - ay

  if (dx === 0 && dy === 0) {
    return Math.hypot(px - ax, py - ay)
  }

  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
  const sx = ax + dx * t
  const sy = ay + dy * t
  return Math.hypot(px - sx, py - sy)
}

function isBlockedPoint(world: WorldModel, point: Vec2): boolean {
  for (const zone of world.zones) {
    if (zone.category === 'restricted' && pointInPolygon(point, zone.polygon)) {
      return true
    }
  }

  for (const wall of world.virtualWalls) {
    if (wall.enabled && distancePointToSegment(point, wall.start, wall.end) <= virtualWallMargin) {
      return true
    }
  }

  return false
}

interface GridCell {
  x: number
  y: number
}

interface GridSpec {
  origin: Vec2
  cols: number
  rows: number
  resolution: number
}

function createGrid(bounds: MapBounds): GridSpec {
  return {
    origin: cloneVec2(bounds.min),
    cols: Math.max(2, Math.round((bounds.max[0] - bounds.min[0]) / gridResolution) + 1),
    rows: Math.max(2, Math.round((bounds.max[1] - bounds.min[1]) / gridResolution) + 1),
    resolution: gridResolution,
  }
}

function cellIndex(cell: GridCell, grid: GridSpec): number {
  return cell.y * grid.cols + cell.x
}

function cellToPoint(cell: GridCell, grid: GridSpec): Vec2 {
  return [
    grid.origin[0] + cell.x * grid.resolution,
    grid.origin[1] + cell.y * grid.resolution,
  ]
}

function pointToCell(point: Vec2, grid: GridSpec): GridCell {
  return {
    x: Math.min(grid.cols - 1, Math.max(0, Math.round((point[0] - grid.origin[0]) / grid.resolution))),
    y: Math.min(grid.rows - 1, Math.max(0, Math.round((point[1] - grid.origin[1]) / grid.resolution))),
  }
}

function isBlockedCell(world: WorldModel, cell: GridCell, grid: GridSpec): boolean {
  const point = cellToPoint(cell, grid)
  return isBlockedPoint(world, point)
}

function nearestOpenCell(world: WorldModel, seed: GridCell, grid: GridSpec): GridCell {
  if (!isBlockedCell(world, seed, grid)) {
    return seed
  }

  for (let radius = 1; radius < 12; radius += 1) {
    for (let offsetY = -radius; offsetY <= radius; offsetY += 1) {
      for (let offsetX = -radius; offsetX <= radius; offsetX += 1) {
        if (Math.abs(offsetX) !== radius && Math.abs(offsetY) !== radius) {
          continue
        }

        const candidate = {
          x: seed.x + offsetX,
          y: seed.y + offsetY,
        }

        if (candidate.x < 0 || candidate.y < 0 || candidate.x >= grid.cols || candidate.y >= grid.rows) {
          continue
        }

        if (!isBlockedCell(world, candidate, grid)) {
          return candidate
        }
      }
    }
  }

  return seed
}

function reconstructPath(cameFrom: Map<number, number>, currentIndex: number, grid: GridSpec): Vec2[] {
  const cells: GridCell[] = []
  let walker = currentIndex

  while (true) {
    cells.push({
      x: walker % grid.cols,
      y: Math.floor(walker / grid.cols),
    })

    const parent = cameFrom.get(walker)
    if (parent === undefined) {
      break
    }

    walker = parent
  }

  return cells.reverse().map((cell) => cellToPoint(cell, grid))
}

function segmentBlocked(world: WorldModel, start: Vec2, end: Vec2): boolean {
  const length = distance(start, end)
  const samples = Math.max(2, Math.ceil(length / pathProbeStep))

  for (let step = 0; step <= samples; step += 1) {
    const t = step / samples
    const point: Vec2 = [
      start[0] + (end[0] - start[0]) * t,
      start[1] + (end[1] - start[1]) * t,
    ]
    if (isBlockedPoint(world, point)) {
      return true
    }
  }

  return false
}

function simplifyCollinear(points: Vec2[]): Vec2[] {
  if (points.length <= 2) {
    return points
  }

  const simplified: Vec2[] = [points[0]]

  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = simplified[simplified.length - 1]
    const current = points[index]
    const next = points[index + 1]
    const cross =
      (current[0] - previous[0]) * (next[1] - current[1]) -
      (current[1] - previous[1]) * (next[0] - current[0])

    if (Math.abs(cross) > 0.01) {
      simplified.push(current)
    }
  }

  simplified.push(points[points.length - 1])
  return simplified
}

function smoothPath(world: WorldModel, points: Vec2[]): Vec2[] {
  if (points.length <= 2) {
    return points
  }

  const smoothed: Vec2[] = [points[0]]
  let anchorIndex = 0

  while (anchorIndex < points.length - 1) {
    let nextIndex = points.length - 1

    while (nextIndex > anchorIndex + 1 && segmentBlocked(world, points[anchorIndex], points[nextIndex])) {
      nextIndex -= 1
    }

    smoothed.push(points[nextIndex])
    anchorIndex = nextIndex
  }

  return simplifyCollinear(smoothed)
}

function heuristic(a: GridCell, b: GridCell): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

function aStarPath(world: WorldModel, start: Vec2, destination: Vec2): Vec2[] {
  const grid = createGrid(world.bounds)
  const startCell = nearestOpenCell(world, pointToCell(start, grid), grid)
  const goalCell = nearestOpenCell(world, pointToCell(destination, grid), grid)
  const startIndex = cellIndex(startCell, grid)
  const goalIndex = cellIndex(goalCell, grid)

  const openSet = new Set<number>([startIndex])
  const cameFrom = new Map<number, number>()
  const gScore = new Map<number, number>([[startIndex, 0]])
  const fScore = new Map<number, number>([[startIndex, heuristic(startCell, goalCell)]])
  const directions: GridCell[] = [
    { x: 1, y: 0 },
    { x: -1, y: 0 },
    { x: 0, y: 1 },
    { x: 0, y: -1 },
    { x: 1, y: 1 },
    { x: 1, y: -1 },
    { x: -1, y: 1 },
    { x: -1, y: -1 },
  ]

  while (openSet.size > 0) {
    let currentIndex = -1
    let currentScore = Number.POSITIVE_INFINITY

    for (const index of openSet) {
      const score = fScore.get(index) ?? Number.POSITIVE_INFINITY
      if (score < currentScore) {
        currentIndex = index
        currentScore = score
      }
    }

    if (currentIndex === goalIndex) {
      const sampled = reconstructPath(cameFrom, currentIndex, grid)
      return smoothPath(world, [start, ...sampled, destination])
    }

    openSet.delete(currentIndex)
    const currentCell = {
      x: currentIndex % grid.cols,
      y: Math.floor(currentIndex / grid.cols),
    }

    for (const direction of directions) {
      const neighbor = {
        x: currentCell.x + direction.x,
        y: currentCell.y + direction.y,
      }

      if (neighbor.x < 0 || neighbor.y < 0 || neighbor.x >= grid.cols || neighbor.y >= grid.rows) {
        continue
      }

      if (isBlockedCell(world, neighbor, grid)) {
        continue
      }

      const neighborIndex = cellIndex(neighbor, grid)
      const tentativeScore = (gScore.get(currentIndex) ?? Number.POSITIVE_INFINITY) + heuristic(currentCell, neighbor)

      if (tentativeScore >= (gScore.get(neighborIndex) ?? Number.POSITIVE_INFINITY)) {
        continue
      }

      cameFrom.set(neighborIndex, currentIndex)
      gScore.set(neighborIndex, tentativeScore)
      fScore.set(neighborIndex, tentativeScore + heuristic(neighbor, goalCell))
      openSet.add(neighborIndex)
    }
  }

  return [start, destination]
}

function advanceTasks(tasks: TaskItem[], active: boolean, missionMode: MissionState['mode']): TaskItem[] {
  if (!active || missionMode === 'scanning') {
    return tasks.map((task) => ({ ...task }))
  }

  const nextTasks = tasks.map((task) => ({ ...task }))
  const runningIndex = nextTasks.findIndex((task) => task.status === 'running')

  if (runningIndex < 0) {
    return nextTasks
  }

  const runningTask = nextTasks[runningIndex]
  const nextProgress = Math.min(100, runningTask.progressPct + 4)
  runningTask.progressPct = nextProgress
  runningTask.etaSec = Math.max(0, runningTask.etaSec - 5)
  runningTask.status = nextProgress >= 100 ? 'done' : 'running'

  if (runningTask.status === 'done') {
    const queuedTask = nextTasks.find((task) => task.status === 'queued')
    if (queuedTask) {
      queuedTask.status = 'running'
      queuedTask.progressPct = Math.max(queuedTask.progressPct, 6)
    }
  }

  return nextTasks
}

function advancePoseAlongPath(runtime: RuntimeState): {
  pose: Pick<RuntimeState['robotPose'], 'x' | 'y' | 'yawRad'>
  pathWaypoints: Vec2[]
  completed: boolean
} {
  const remaining = runtime.path.waypoints.map(cloneVec2)
  let current: Vec2 = [runtime.robotPose.x, runtime.robotPose.y]

  while (remaining.length > 0 && distance(current, remaining[0]) < 0.14) {
    remaining.shift()
  }

  if (remaining.length === 0) {
    return {
      pose: {
        x: runtime.robotPose.x,
        y: runtime.robotPose.y,
        yawRad: runtime.robotPose.yawRad,
      },
      pathWaypoints: [],
      completed: true,
    }
  }

  let moveBudget = 0.26
  let x = runtime.robotPose.x
  let y = runtime.robotPose.y
  let yawRad = runtime.robotPose.yawRad

  while (moveBudget > 0 && remaining.length > 0) {
    const target = remaining[0]
    const toTarget = distance([x, y], target)

    if (toTarget === 0) {
      remaining.shift()
      continue
    }

    yawRad = Math.atan2(target[1] - y, target[0] - x)

    if (toTarget <= moveBudget) {
      x = target[0]
      y = target[1]
      moveBudget -= toTarget
      remaining.shift()
      current = [x, y]
      continue
    }

    x += Math.cos(yawRad) * moveBudget
    y += Math.sin(yawRad) * moveBudget
    moveBudget = 0
    current = [x, y]
  }

  return {
    pose: { x, y, yawRad },
    pathWaypoints: remaining.length > 0 ? [current, ...remaining] : [],
    completed: remaining.length === 0,
  }
}

function seedTasks(): TaskItem[] {
  return [
    { id: 'task-demo', title: '路径规划验证', status: 'running', progressPct: 18, etaSec: 90 },
  ]
}

export function createConversationMessage(
  role: ConversationMessage['role'],
  content: string,
  timestamp = formatTimestamp(),
): ConversationMessage {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`,
    role,
    content,
    timestamp,
  }
}

export function createPatrolPath(world: WorldModel): Vec2[] {
  if (world.mapping.status !== 'ready') {
    return []
  }

  return patrolLoop.map(cloneVec2)
}

export function getZoneAnchor(world: WorldModel, zoneId: string): Vec2 | null {
  const zone = world.zones.find((item) => item.id === zoneId)
  if (!zone) {
    return null
  }

  return zone.labelAnchor ? cloneVec2(zone.labelAnchor) : polygonCentroid(zone.polygon)
}

export function findZoneAtPoint(world: WorldModel, point: Vec2): MapZone | null {
  for (const zone of world.zones) {
    if (pointInPolygon(point, zone.polygon)) {
      return zone
    }
  }

  const selectableZones = world.zones.filter((zone) => zone.selectable)
  if (selectableZones.length === 0) {
    return null
  }

  return selectableZones.reduce((closest, candidate) => {
    const closestPoint = closest.labelAnchor ?? polygonCentroid(closest.polygon)
    const candidatePoint = candidate.labelAnchor ?? polygonCentroid(candidate.polygon)
    return distance(point, candidatePoint) < distance(point, closestPoint) ? candidate : closest
  })
}

export function buildNavigationPath(world: WorldModel, start: Vec2, destination: Vec2): Vec2[] {
  if (world.mapping.status !== 'ready') {
    return [cloneVec2(start)]
  }

  const safeStart = clampPointToBounds(start, world.bounds)
  const safeDestination = clampPointToBounds(destination, world.bounds)
  if (!segmentBlocked(world, safeStart, safeDestination)) {
    return [safeStart, safeDestination]
  }

  return aStarPath(world, safeStart, safeDestination)
}

export function createMappedWorldModel(): WorldModel {
  return {
    mapId: 'hq-floor-01',
    mapName: '总部一层样例地图',
    bounds: computeBoundsFromZones(mappedZones),
    zones: mappedZones.map(cloneZone),
    regionLabels: mappedRegionLabels.map(cloneLabel),
    virtualWalls: mappedWalls.map(cloneWall),
    mapping: {
      status: 'ready',
      progressPct: 100,
      hint: '地图已完成建模，可右键设置目的地、添加区域标签或绘制虚拟墙。',
      lastCompletedAt: Date.now(),
    },
  }
}

export function createMockWorldModel(): WorldModel {
  return {
    mapId: 'workspace-pending',
    mapName: '未建模工作区',
    bounds: {
      min: cloneVec2(emptyBounds.min),
      max: cloneVec2(emptyBounds.max),
    },
    zones: [],
    regionLabels: [],
    virtualWalls: [],
    mapping: {
      status: 'unmapped',
      progressPct: 0,
      hint: '地图区域为空，请先执行一键全屋扫描完成建模。',
      lastCompletedAt: null,
    },
  }
}

export function createMockSnapshot(): RoverSnapshot {
  const world = createMappedWorldModel()
  const start: Vec2 = [1.8, 1.2]
  const destination = getZoneAnchor(world, 'inspection-east') ?? [12.4, 5.5]
  const demoPath = buildNavigationPath(world, start, destination)

  return {
    world,
    runtime: {
      robotPose: {
        x: start[0],
        y: start[1],
        yawRad: 0,
        linearVelocity: 0.24,
        angularVelocity: 0,
        frameId: 'map',
        stampMs: Date.now(),
      },
      path: {
        id: 'path-demo',
        status: 'executing',
        waypoints: demoPath,
        destination,
        algorithm: 'A* + 虚拟墙避让',
        lastUpdatedMs: Date.now(),
      },
      lidar: {
        frameId: 'map',
        stampMs: Date.now(),
        maxRangeM: 5.2,
        points: makeLidar({ x: start[0], y: start[1] }, 0),
      },
      camera: seedCamera(),
      telemetry: {
        batteryPercent: 87,
        cpuPercent: 29,
        temperatureC: 43,
        networkRttMs: 32,
        localizationConfidence: 0.66,
        motorCurrentA: 0.8,
      },
      mission: seedMission(),
      tasks: seedTasks(),
      voice: seedVoice(),
      selectedZoneId: 'inspection-east',
      conversationHistory: seedConversationHistory(),
    },
  }
}

export function advanceMockRuntime(previous: RuntimeState, world: WorldModel, tick: number): RuntimeState {
  let nextPose = {
    x: previous.robotPose.x,
    y: previous.robotPose.y,
    yawRad: previous.robotPose.yawRad,
  }
  let nextPath = {
    ...previous.path,
    waypoints: previous.path.waypoints.map(cloneVec2),
  }

  const canMove = previous.path.status === 'executing' && previous.path.waypoints.length > 0 && previous.mission.mode !== 'paused'
  if (canMove) {
    const advanced = advancePoseAlongPath(previous)
    nextPose = advanced.pose
    nextPath = {
      ...nextPath,
      waypoints: advanced.pathWaypoints,
      status: advanced.completed ? 'completed' : 'executing',
      lastUpdatedMs: Date.now(),
    }

    if (advanced.completed && previous.path.id.startsWith('patrol') && world.mapping.status === 'ready') {
      nextPath = {
        id: previous.path.id,
        status: 'executing',
        waypoints: createPatrolPath(world),
        destination: null,
        algorithm: previous.path.algorithm,
        lastUpdatedMs: Date.now(),
      }
    }
  }

  const derivedZone = world.mapping.status === 'ready' ? findZoneAtPoint(world, [nextPose.x, nextPose.y]) : null
  const activeMotion = nextPath.status === 'executing'

  return {
    ...previous,
    robotPose: {
      ...previous.robotPose,
      ...nextPose,
      linearVelocity: activeMotion ? 0.34 + Math.abs(Math.sin(tick * 0.13)) * 0.12 : 0,
      angularVelocity: activeMotion ? Math.sin(tick * 0.09) * 0.18 : 0,
      stampMs: Date.now(),
    },
    path: nextPath,
    lidar: {
      ...previous.lidar,
      stampMs: Date.now(),
      points: makeLidar(nextPose, tick),
    },
    camera: {
      ...previous.camera,
      frameUrl: cameraFrame(
        world.mapping.status === 'ready'
          ? `NAV / ${activeMotion ? 'EXECUTING' : 'READY'} / ${tick}`
          : `SCAN / WAIT / ${tick}`,
      ),
      fps: 16 + (tick % 6),
      latencyMs: 88 + (tick % 7) * 8,
    },
    telemetry: {
      batteryPercent: Math.max(16, previous.telemetry.batteryPercent - (activeMotion ? 0.018 : 0.005)),
      cpuPercent:
        world.mapping.status === 'scanning'
          ? 46 + Math.abs(Math.sin(tick * 0.16)) * 24
          : 31 + Math.abs(Math.sin(tick * 0.13)) * 28,
      temperatureC:
        world.mapping.status === 'scanning'
          ? 46 + Math.abs(Math.sin(tick * 0.18)) * 9
          : 42 + Math.abs(Math.sin(tick * 0.18)) * 7,
      networkRttMs: 24 + Math.abs(Math.sin(tick * 0.08)) * 22,
      localizationConfidence:
        world.mapping.status === 'ready'
          ? 0.89 + Math.abs(Math.cos(tick * 0.05)) * 0.08
          : 0.58 + Math.abs(Math.cos(tick * 0.05)) * 0.1,
      motorCurrentA: activeMotion ? 1.4 + Math.abs(Math.sin(tick * 0.16)) * 1.2 : 0.7,
    },
    tasks: advanceTasks(previous.tasks, activeMotion, previous.mission.mode),
    selectedZoneId: derivedZone?.id ?? previous.selectedZoneId,
  }
}
