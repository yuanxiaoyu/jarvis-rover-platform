import type {
  CameraPanelState,
  LidarPoint,
  MapZone,
  MissionState,
  RoverSnapshot,
  RuntimeState,
  TaskItem,
  Vec2,
  VirtualWall,
  VoiceState,
  WorldModel,
} from '@/types/contract'

const mapZones: MapZone[] = [
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
    ] as Vec2[],
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
    ] as Vec2[],
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
    ] as Vec2[],
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
    ] as Vec2[],
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
    ] as Vec2[],
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
    ] as Vec2[],
  },
]

const virtualWalls: VirtualWall[] = [
  {
    id: 'wall-a',
    name: '通道缓冲虚拟墙',
    start: [3.6, 1.2] as Vec2,
    end: [3.6, 3.4] as Vec2,
    height: 1.1,
    enabled: true,
  },
  {
    id: 'wall-b',
    name: '维护围栏',
    start: [10.6, 9.2] as Vec2,
    end: [14.8, 9.2] as Vec2,
    height: 1.3,
    enabled: true,
  },
  {
    id: 'wall-c',
    name: '软限制区域',
    start: [11.8, 6.2] as Vec2,
    end: [14.2, 8.2] as Vec2,
    height: 0.8,
    enabled: false,
  },
]

const routeLoop: Vec2[] = [
  [1.8, 1.2],
  [5.2, 1.2],
  [5.2, 6],
  [10.8, 6],
  [10.8, 10.8],
  [5.2, 10.8],
  [5.2, 6],
  [1.8, 6],
]

const seedTasks: TaskItem[] = [
  { id: 'task-localize', title: '定位预热', status: 'done', progressPct: 100, etaSec: 0 },
  { id: 'task-patrol', title: '主通道巡航', status: 'running', progressPct: 48, etaSec: 240 },
  { id: 'task-lidar', title: '雷达质量扫描', status: 'queued', progressPct: 0, etaSec: 420 },
  { id: 'task-dock', title: '返航回桩', status: 'queued', progressPct: 0, etaSec: 600 },
]

function computeBoundsFromZones(zones: { polygon: Vec2[] }[]): { min: Vec2; max: Vec2 } {
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

  return {
    min: [minX, minY],
    max: [maxX, maxY],
  }
}

function cameraFrame(label: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="192" viewBox="0 0 320 192">
    <defs>
      <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
        <stop stop-color="#13242a" offset="0"/>
        <stop stop-color="#244449" offset="0.45"/>
        <stop stop-color="#10201f" offset="1"/>
      </linearGradient>
    </defs>
    <rect width="320" height="192" fill="url(#g)"/>
    <rect x="14" y="16" width="292" height="160" rx="10" fill="none" stroke="#6ad4c4" stroke-opacity="0.44"/>
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
    transcript: '语音待命中',
    confidence: 0,
  }
}

function seedMission(): MissionState {
  return {
    mode: 'autonomy',
    objective: '巡航主通道并检查东侧巡检区',
    statusLine: '任务状态正常',
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
    fps: 20,
    latencyMs: 110,
  }
}

function makeLidar(pose: { x: number; y: number }, tick: number): LidarPoint[] {
  const points: LidarPoint[] = []
  const count = 230

  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2 + tick * 0.07
    const range = 1.2 + 2.7 * Math.abs(Math.sin(i * 0.17 + tick * 0.09))
    const noise = Math.sin(i * 0.91 + tick * 0.23) * 0.08
    points.push({
      x: pose.x + Math.cos(angle) * (range + noise),
      y: pose.y + Math.sin(angle) * (range + noise),
      intensity: 0.4 + 0.6 * Math.abs(Math.sin(i * 0.31 + tick * 0.11)),
    })
  }

  return points
}

function interpolatePath(path: Vec2[], step: number): { x: number; y: number; yawRad: number } {
  const segment = step % path.length
  const start = path[segment]
  const end = path[(segment + 1) % path.length]
  const phase = (Math.sin(step * 0.2) + 1) * 0.5
  const x = start[0] + (end[0] - start[0]) * phase
  const y = start[1] + (end[1] - start[1]) * phase
  const yawRad = Math.atan2(end[1] - start[1], end[0] - start[0])

  return { x, y, yawRad }
}

export function createMockWorldModel(): WorldModel {
  const bounds = computeBoundsFromZones(mapZones)
  return {
    mapId: 'hq-floor-01',
    mapName: '总部一层样例地图',
    bounds,
    zones: mapZones,
    virtualWalls,
  }
}

export function createMockSnapshot(): RoverSnapshot {
  const world = createMockWorldModel()
  const pose = interpolatePath(routeLoop, 0)
  return {
    world,
    runtime: {
      robotPose: {
        ...pose,
        linearVelocity: 0.48,
        angularVelocity: 0.06,
        frameId: 'map',
        stampMs: Date.now(),
      },
      path: {
        id: 'path-primary',
        status: 'executing',
        waypoints: routeLoop,
      },
      lidar: {
        frameId: 'map',
        stampMs: Date.now(),
        maxRangeM: 5.2,
        points: makeLidar(pose, 0),
      },
      camera: seedCamera(),
      telemetry: {
        batteryPercent: 84,
        cpuPercent: 41,
        temperatureC: 47,
        networkRttMs: 34,
        localizationConfidence: 0.93,
        motorCurrentA: 1.9,
      },
      mission: seedMission(),
      tasks: seedTasks,
      voice: seedVoice(),
      selectedZoneId: 'inspection-east',
    },
  }
}

export function advanceMockRuntime(previous: RuntimeState, world: WorldModel, tick: number): RuntimeState {
  const nextPose = interpolatePath(previous.path.waypoints, tick)
  const batteryDrop = (tick % 500) / 5000
  const runningTaskIndex = previous.tasks.findIndex((task) => task.status === 'running')

  const nextTasks: TaskItem[] = previous.tasks.map((task, index): TaskItem => {
    if (index !== runningTaskIndex) {
      return task
    }

    const progress = Math.min(100, task.progressPct + 2)
    const status: TaskItem['status'] = progress >= 100 ? 'done' : 'running'
    return {
      ...task,
      progressPct: progress,
      etaSec: Math.max(0, task.etaSec - 6),
      status,
    }
  })

  if (runningTaskIndex >= 0 && nextTasks[runningTaskIndex]?.status === 'done') {
    const queuedIndex = nextTasks.findIndex((task) => task.status === 'queued')
    if (queuedIndex >= 0) {
      nextTasks[queuedIndex] = {
        ...nextTasks[queuedIndex],
        status: 'running',
        progressPct: 2,
      }
    }
  }

  const zoneRotation = world.zones.filter((zone) => zone.selectable)
  const rotatedZone = zoneRotation[tick % zoneRotation.length]

  return {
    ...previous,
    robotPose: {
      ...previous.robotPose,
      ...nextPose,
      linearVelocity: 0.38 + Math.abs(Math.sin(tick * 0.1)) * 0.24,
      angularVelocity: Math.sin(tick * 0.13) * 0.22,
      stampMs: Date.now(),
    },
    lidar: {
      ...previous.lidar,
      stampMs: Date.now(),
      points: makeLidar(nextPose, tick),
    },
    camera: {
      ...previous.camera,
      frameUrl: cameraFrame(`FRONT_CAM / TICK ${tick}`),
      fps: 18 + (tick % 6),
      latencyMs: 95 + (tick % 8) * 8,
    },
    telemetry: {
      batteryPercent: Math.max(12, previous.telemetry.batteryPercent - batteryDrop),
      cpuPercent: 34 + Math.abs(Math.sin(tick * 0.13)) * 46,
      temperatureC: 42 + Math.abs(Math.sin(tick * 0.18)) * 18,
      networkRttMs: 24 + Math.abs(Math.sin(tick * 0.08)) * 52,
      localizationConfidence: 0.84 + Math.abs(Math.cos(tick * 0.05)) * 0.13,
      motorCurrentA: 1.3 + Math.abs(Math.sin(tick * 0.16)) * 1.8,
    },
    tasks: nextTasks,
    selectedZoneId: rotatedZone?.id ?? previous.selectedZoneId,
  }
}
