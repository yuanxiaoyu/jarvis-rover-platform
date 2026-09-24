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

export interface OccupancyLayer {
  width: number
  height: number
  resolution: number
  origin: Vec2
  originYaw?: number
  data: ArrayLike<number> | null
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

/** Compatibility shape retained for the existing system snapshot contract. */
export interface VoiceState {
  listening: boolean
  wakeWordArmed: boolean
  transcript: string
  confidence: number
}

export type VoiceLifecycleState =
  | 'disabled'
  | 'wake_listening'
  | 'capturing'
  | 'processing_asr'
  | 'processing_assistant'
  | 'speaking'
  | 'audio_unavailable'
  | 'asr_error'
  | 'assistant_unavailable'
  | 'tts_error'

export type VoiceErrorCode =
  | 'assistant_unavailable'
  | 'command_rejected'
  | 'invalid_decision'
  | 'voice_unauthorized'
  | 'audio_unavailable'
  | 'asr_error'
  | 'tts_error'

export interface VoiceError {
  code: VoiceErrorCode
  message: string
  recoverable: boolean
}

export interface VoiceStatus {
  schemaVersion: 1
  state: VoiceLifecycleState
  enabled: boolean
  sessionId: string | null
  turnId: string | null
  lastError: VoiceError | null
  componentLatencyMs: Record<string, number | null>
  receivedAt: string
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
  occupancy?: OccupancyLayer | null
}

export interface RuntimeState {
  robotPose: RobotPose
  poseAvailable?: boolean
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

const VOICE_STATES: readonly VoiceLifecycleState[] = [
  'disabled', 'wake_listening', 'capturing', 'processing_asr', 'processing_assistant',
  'speaking', 'audio_unavailable', 'asr_error', 'assistant_unavailable', 'tts_error',
]
const ERROR_CODES: readonly VoiceErrorCode[] = [
  'assistant_unavailable', 'command_rejected', 'invalid_decision', 'voice_unauthorized',
  'audio_unavailable', 'asr_error', 'tts_error',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseError(value: unknown): VoiceError | null {
  if (value === null) return null
  if (!isRecord(value) || typeof value.code !== 'string' || !ERROR_CODES.includes(value.code as VoiceErrorCode)) {
    throw new Error('invalid voice error')
  }
  if (typeof value.message !== 'string' || value.message.length === 0 || value.message.length > 500) {
    throw new Error('invalid voice error message')
  }
  if (typeof value.recoverable !== 'boolean') throw new Error('invalid voice error recoverability')
  return { code: value.code as VoiceErrorCode, message: value.message, recoverable: value.recoverable }
}

export function parseVoiceStatus(value: unknown): VoiceStatus {
  if (!isRecord(value) || value.schema_version !== 1 || typeof value.state !== 'string' || !VOICE_STATES.includes(value.state as VoiceLifecycleState)) {
    throw new Error('invalid voice status schema')
  }
  if (typeof value.enabled !== 'boolean') throw new Error('invalid voice enabled state')
  if (value.session_id !== null && typeof value.session_id !== 'string') throw new Error('invalid voice session id')
  if (value.turn_id !== null && typeof value.turn_id !== 'string') throw new Error('invalid voice turn id')
  if (typeof value.received_at !== 'string' || Number.isNaN(Date.parse(value.received_at))) throw new Error('invalid voice timestamp')
  if (!isRecord(value.component_latency_ms)) throw new Error('invalid voice latency')
  const componentLatencyMs: Record<string, number | null> = {}
  for (const [name, latency] of Object.entries(value.component_latency_ms)) {
    if (latency !== null && (typeof latency !== 'number' || !Number.isFinite(latency) || latency < 0)) {
      throw new Error(`invalid latency for ${name}`)
    }
    componentLatencyMs[name] = latency as number | null
  }
  return {
    schemaVersion: 1,
    state: value.state as VoiceLifecycleState,
    enabled: value.enabled,
    sessionId: value.session_id as string | null,
    turnId: value.turn_id as string | null,
    lastError: parseError(value.last_error),
    componentLatencyMs,
    receivedAt: value.received_at,
  }
}
