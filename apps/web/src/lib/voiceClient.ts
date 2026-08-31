import type { VoiceStatus } from '@/types/contract'

const STATES = new Set<VoiceStatus['state']>([
  'disabled', 'wake_listening', 'capturing', 'processing_asr',
  'processing_assistant', 'speaking', 'audio_unavailable', 'asr_error',
  'assistant_unavailable', 'tts_error',
])

export function parseVoiceStatus(value: unknown): VoiceStatus {
  if (!value || typeof value !== 'object') throw new Error('invalid voice status')
  const input = value as Record<string, unknown>
  if (input.schema_version !== 1 || typeof input.state !== 'string' || !STATES.has(input.state as VoiceStatus['state'])) {
    throw new Error('unsupported voice status schema')
  }
  if (typeof input.enabled !== 'boolean') throw new Error('invalid voice enabled flag')
  const error = input.last_error
  if (error !== null && error !== undefined) {
    if (typeof error !== 'object') throw new Error('invalid voice error')
    const item = error as Record<string, unknown>
    if (typeof item.code !== 'string' || typeof item.message !== 'string' || typeof item.recoverable !== 'boolean') {
      throw new Error('invalid voice error')
    }
  }
  const latencies = input.component_latency_ms
  if (!latencies || typeof latencies !== 'object' || Object.values(latencies).some((v) => v !== null && typeof v !== 'number')) {
    throw new Error('invalid voice latency')
  }
  return {
    schema_version: 1,
    state: input.state as VoiceStatus['state'],
    enabled: input.enabled,
    session_id: typeof input.session_id === 'string' ? input.session_id : null,
    turn_id: typeof input.turn_id === 'string' ? input.turn_id : null,
    last_error: (error ?? null) as VoiceStatus['last_error'],
    component_latency_ms: latencies as Record<string, number | null>,
    received_at: typeof input.received_at === 'string' ? input.received_at : new Date().toISOString(),
  }
}

export async function fetchVoiceStatus(baseUrl = '', signal?: AbortSignal): Promise<VoiceStatus> {
  const response = await fetch(`${baseUrl}/api/v1/voice/status`, { signal })
  if (!response.ok) throw new Error(`voice status ${response.status}`)
  return parseVoiceStatus(await response.json())
}

export class VoiceClient {
  constructor(private readonly baseUrl = '') {}

  getStatus(signal?: AbortSignal): Promise<VoiceStatus> {
    return fetchVoiceStatus(this.baseUrl, signal)
  }
}
