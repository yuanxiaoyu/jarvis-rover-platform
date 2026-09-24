export type Vec2 = [number, number]

export interface RealZone {
  id: string
  name: string
  type: string
  semanticLabel: string | null
  points: Vec2[]
  keepoutEnabled: boolean
  virtualWallEnabled: boolean
}

export interface RealWall {
  id: string
  name: string
  points: Vec2[]
  enabled: boolean
}

export interface RealTask {
  id: string
  type: string
  status: string
  description: string
  createdAt: string
  updatedAt: string
}

export interface OccupancyGrid {
  resolution: number
  width: number
  height: number
  origin: Vec2
  originYaw: number
  frameId: string
  data: number[] | null
}

export interface RealRobotPose {
  available: boolean
  x: number | null
  y: number | null
  yawRad: number | null
  linearVelocityMps: number | null
  angularVelocityRadps: number | null
  timestamp: string | null
  error: string | null
}

export interface RealSnapshot {
  mapId: string
  mapName: string
  mapSource: string
  mapUpdatedAt: string
  mapAvailable: boolean
  occupancy: OccupancyGrid
  mapping: {
    sessionId: string | null
    state: string
    ready: boolean
    motionAllowed: boolean
    mapUpdateAgeS: number | null
    currentRevision: string | null
    lastError: string
  }
  robotPose: RealRobotPose
  mapBounds: { min: Vec2; max: Vec2 }
  zones: RealZone[]
  walls: RealWall[]
  tasks: RealTask[]
  mission: {
    mode: string
    objective: string
    statusLine: string
    selectedZoneId: string | null
    explorationState: 'idle' | 'starting' | 'exploring' | 'paused' | 'complete' | 'stopped' | 'error'
    explorationMessage: string
    currentTarget: Vec2 | null
    completedFrontiers: number
    failedFrontiers: number
    remainingFrontiers: number
  }
  sensor: {
    available: boolean
    error: string | null
    batteryPercent: number | null
    voltageV: number | null
    charging: boolean | null
    boardTemperatureC: number | null
    motorTemperatureC: number | null
    yawRad: number | null
    lidarPoints: number | null
    lidarQuality: number | null
    timestamp: string
  }
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error(`invalid ${label}`)
  return value as Record<string, unknown>
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new Error(`invalid ${label}`)
  return value
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null
  return stringValue(value, label)
}

function numberOrNull(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`invalid ${label}`)
  return value
}

function boolOrNull(value: unknown, label: string): boolean | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'boolean') throw new Error(`invalid ${label}`)
  return value
}

function point(value: unknown, label: string): Vec2 {
  const item = record(value, label)
  const x = numberOrNull(item.x, `${label}.x`)
  const y = numberOrNull(item.y, `${label}.y`)
  if (x === null || y === null) throw new Error(`invalid ${label}`)
  return [x, y]
}

function parsePoints(value: unknown, label: string): Vec2[] {
  if (!Array.isArray(value)) throw new Error(`invalid ${label}`)
  return value.map((item) => point(item, label))
}

export function parseRealSnapshot(value: unknown): RealSnapshot {
  const root = record(value, 'snapshot')
  const map = record(root.map, 'map')
  const occupancy = record(map.occupancy, 'map occupancy')
  const origin = record(occupancy.origin, 'map origin')
  const mission = record(root.mission, 'mission')
  const sensor = record(root.sensor, 'sensor')
  const mapping = record(root.mapping, 'mapping')
  const robotPose = record(root.robot_pose, 'robot pose')
  const battery = record(sensor.battery, 'battery')
  const temperature = record(sensor.temperature, 'temperature')
  const imu = record(sensor.imu, 'imu')
  const lidar = record(sensor.lidar, 'lidar')
  if (!Array.isArray(root.zones) || !Array.isArray(root.tasks)) throw new Error('invalid snapshot collections')

  const resolution = numberOrNull(occupancy.resolution_m_per_cell, 'map resolution')
  const width = numberOrNull(occupancy.width_cells, 'map width')
  const height = numberOrNull(occupancy.height_cells, 'map height')
  const originX = numberOrNull(origin.x, 'map origin x')
  const originY = numberOrNull(origin.y, 'map origin y')
  const originYaw = numberOrNull(origin.yaw_rad, 'map origin yaw') ?? 0
  if (resolution === null || width === null || height === null || originX === null || originY === null) {
    throw new Error('map geometry is unavailable')
  }
  const rawGrid = occupancy.data
  let gridData: number[] | null = null
  if (rawGrid !== null && rawGrid !== undefined) {
    if (!Array.isArray(rawGrid) || rawGrid.length !== width * height) throw new Error('invalid occupancy grid data')
    gridData = rawGrid.map((cell) => {
      if (typeof cell !== 'number' || !Number.isInteger(cell) || cell < -1 || cell > 100) throw new Error('invalid occupancy value')
      return cell
    })
  }
  const zones = root.zones.map((raw) => {
    const zone = record(raw, 'zone')
    return {
      id: stringValue(zone.zone_id, 'zone id'),
      name: stringValue(zone.name, 'zone name'),
      type: stringValue(zone.type, 'zone type'),
      semanticLabel: nullableString(zone.semantic_label, 'zone semantic label'),
      points: parsePoints(zone.points, 'zone points'),
      keepoutEnabled: boolOrNull(zone.nav2_keepout_enabled, 'zone keepout state') ?? false,
      virtualWallEnabled: boolOrNull(zone.nav2_virtual_wall_enabled, 'zone virtual wall state') ?? false,
    }
  })
  const walls = zones
    .filter((zone) => zone.virtualWallEnabled)
    .map((zone) => ({ id: zone.id, name: zone.name, points: zone.points, enabled: true }))
  const tasks = root.tasks.map((raw) => {
    const task = record(raw, 'task')
    return {
      id: stringValue(task.task_id, 'task id'),
      type: stringValue(task.type, 'task type'),
      status: stringValue(task.status, 'task status'),
      description: typeof task.description === 'string' ? task.description : '',
      createdAt: stringValue(task.created_at, 'task created time'),
      updatedAt: stringValue(task.updated_at, 'task updated time'),
    }
  })
  const explorationTarget = mission.current_target === null || mission.current_target === undefined
    ? null
    : point(mission.current_target, 'mission.current_target')
  const explorationState = typeof mission.exploration_state === 'string' ? mission.exploration_state : 'idle'
  const validExplorationStates = ['idle', 'starting', 'exploring', 'paused', 'complete', 'stopped', 'error'] as const

  const mapWidthM = width * resolution
  const mapHeightM = height * resolution
  const cosine = Math.cos(originYaw)
  const sine = Math.sin(originYaw)
  const mapCorners: Vec2[] = [
    [0, 0],
    [mapWidthM, 0],
    [0, mapHeightM],
    [mapWidthM, mapHeightM],
  ].map(([localX, localY]) => [
    originX + cosine * localX - sine * localY,
    originY + sine * localX + cosine * localY,
  ])

  return {
    mapId: stringValue(map.map_id, 'map id'),
    mapName: stringValue(map.name, 'map name'),
    mapSource: stringValue(map.source, 'map source'),
    mapUpdatedAt: stringValue(map.updated_at, 'map update time'),
    mapAvailable: typeof map.available === 'boolean' ? map.available : gridData !== null,
    occupancy: {
      resolution,
      width,
      height,
      origin: [originX, originY],
      originYaw,
      frameId: typeof occupancy.frame_id === 'string' ? occupancy.frame_id : 'map',
      data: gridData,
    },
    mapping: {
      sessionId: nullableString(mapping.session_id, 'mapping session id'),
      state: stringValue(mapping.state, 'mapping state'),
      ready: typeof mapping.ready === 'boolean' ? mapping.ready : false,
      motionAllowed: typeof mapping.motion_allowed === 'boolean' ? mapping.motion_allowed : false,
      mapUpdateAgeS: numberOrNull(mapping.map_update_age_s, 'map update age'),
      currentRevision: nullableString(mapping.current_revision, 'map revision'),
      lastError: typeof mapping.last_error === 'string' ? mapping.last_error : '',
    },
    robotPose: {
      available: typeof robotPose.available === 'boolean' ? robotPose.available : false,
      x: numberOrNull(robotPose.x, 'robot pose x'),
      y: numberOrNull(robotPose.y, 'robot pose y'),
      yawRad: numberOrNull(robotPose.yaw_rad, 'robot pose yaw'),
      linearVelocityMps: numberOrNull(robotPose.linear_velocity_mps, 'robot linear velocity'),
      angularVelocityRadps: numberOrNull(robotPose.angular_velocity_radps, 'robot angular velocity'),
      timestamp: nullableString(robotPose.timestamp, 'robot pose timestamp'),
      error: nullableString(robotPose.error, 'robot pose error'),
    },
    mapBounds: {
      min: [Math.min(...mapCorners.map(([x]) => x)), Math.min(...mapCorners.map(([, y]) => y))],
      max: [Math.max(...mapCorners.map(([x]) => x)), Math.max(...mapCorners.map(([, y]) => y))],
    },
    zones,
    walls,
    tasks,
    mission: {
      mode: stringValue(mission.mode, 'mission mode'),
      objective: stringValue(mission.objective, 'mission objective'),
      statusLine: stringValue(mission.status_line, 'mission status'),
      selectedZoneId: nullableString(mission.selected_zone_id, 'selected zone'),
      explorationState: validExplorationStates.includes(explorationState as typeof validExplorationStates[number])
        ? explorationState as typeof validExplorationStates[number]
        : 'error',
      explorationMessage: typeof mission.exploration_message === 'string' ? mission.exploration_message : '自主探索状态未知',
      currentTarget: explorationTarget,
      completedFrontiers: typeof mission.completed_frontiers === 'number' ? mission.completed_frontiers : 0,
      failedFrontiers: typeof mission.failed_frontiers === 'number' ? mission.failed_frontiers : 0,
      remainingFrontiers: typeof mission.remaining_frontiers === 'number' ? mission.remaining_frontiers : 0,
    },
    sensor: {
      available: typeof sensor.available === 'boolean' ? sensor.available : false,
      error: nullableString(sensor.error, 'sensor error'),
      batteryPercent: numberOrNull(battery.percent, 'battery percent'),
      voltageV: numberOrNull(battery.voltage_v, 'battery voltage'),
      charging: boolOrNull(battery.charging, 'charging state'),
      boardTemperatureC: numberOrNull(temperature.board_c, 'board temperature'),
      motorTemperatureC: numberOrNull(temperature.motor_c, 'motor temperature'),
      yawRad: numberOrNull(imu.yaw_rad, 'IMU yaw'),
      lidarPoints: numberOrNull(lidar.points_2d, 'lidar points'),
      lidarQuality: numberOrNull(lidar.map_quality, 'lidar quality'),
      timestamp: stringValue(sensor.timestamp, 'sensor timestamp'),
    },
  }
}

export async function fetchRealSnapshot(baseUrl = ''): Promise<RealSnapshot> {
  const response = await fetch(`${baseUrl}/api/v1/system/snapshot`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`snapshot request failed (${response.status})`)
  return parseRealSnapshot(await response.json() as unknown)
}
