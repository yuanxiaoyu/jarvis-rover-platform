export type Vec2 = [number, number]

export interface MapBounds {
  min: Vec2
  max: Vec2
}

export interface MapZone {
  id: string
  name: string
  category: 'lane' | 'room' | 'dock' | 'charging' | 'inspection' | 'restricted'
  polygon: Vec2[]
  labelAnchor?: Vec2
  selectable: boolean
}

export interface VirtualWall {
  id: string
  name: string
  start: Vec2
  end: Vec2
  height: number
  enabled: boolean
}

export interface RobotPose {
  x: number
  y: number
  yawRad: number
  linearVelocity: number
  angularVelocity: number
  frameId: string
  stampMs: number
}

export interface PathState {
  id: string
  status: 'idle' | 'planned' | 'executing' | 'paused' | 'completed' | 'aborted'
  waypoints: Vec2[]
}

export interface LidarPoint {
  x: number
  y: number
  intensity: number
}

export interface LidarScan {
  frameId: string
  stampMs: number
  maxRangeM: number
  points: LidarPoint[]
}

export interface CameraPanelState {
  sourceId: string
  title: string
  connected: boolean
  frameUrl: string
  width: number
  height: number
  fps: number
  latencyMs: number
}

export interface TelemetryState {
  batteryPercent: number
  cpuPercent: number
  temperatureC: number
  networkRttMs: number
  localizationConfidence: number
  motorCurrentA: number
}

export interface VoiceState {
  listening: boolean
  wakeWordArmed: boolean
  transcript: string
  confidence: number
}

export interface TaskItem {
  id: string
  title: string
  status: 'queued' | 'running' | 'blocked' | 'done'
  progressPct: number
  etaSec: number
}

export interface MissionState {
  mode: 'idle' | 'autonomy' | 'manual' | 'paused' | 'returning'
  objective: string
  statusLine: string
}

export interface WorldModel {
  mapId: string
  mapName: string
  bounds: MapBounds
  zones: MapZone[]
  virtualWalls: VirtualWall[]
}

export interface RuntimeState {
  robotPose: RobotPose
  path: PathState
  lidar: LidarScan
  camera: CameraPanelState
  telemetry: TelemetryState
  mission: MissionState
  tasks: TaskItem[]
  voice: VoiceState
  selectedZoneId: string | null
}

export interface RoverSnapshot {
  world: WorldModel
  runtime: RuntimeState
}

export interface SendMissionCommandPayload {
  command: 'start' | 'pause' | 'resume' | 'abort' | 'return_home'
}

export interface AiCommandPayload {
  prompt: string
}

export interface VoiceCommandPayload {
  action: 'start' | 'stop'
}

export interface ZoneSelectionPayload {
  zoneId: string | null
}

export interface RoverApiClient {
  fetchBootstrap(): Promise<RoverSnapshot>
  sendMissionCommand(payload: SendMissionCommandPayload): Promise<MissionState>
  submitAiCommand(payload: AiCommandPayload): Promise<{ accepted: boolean; message: string }>
  sendVoiceCommand(payload: VoiceCommandPayload): Promise<VoiceState>
  updateZoneSelection(payload: ZoneSelectionPayload): Promise<{ selectedZoneId: string | null }>
}

export interface SocketEventMap {
  runtime: RuntimeState
  telemetry: TelemetryState
  tasks: TaskItem[]
}

export interface RoverSocketClient {
  connect(): Promise<void>
  disconnect(): void
  subscribe<K extends keyof SocketEventMap>(
    event: K,
    callback: (payload: SocketEventMap[K]) => void,
  ): () => void
}
