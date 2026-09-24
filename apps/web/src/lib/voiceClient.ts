import { parseVoiceStatus, type VoiceStatus } from '@/types/contract'

export function unavailableVoiceStatus(message = '语音服务不可用'): VoiceStatus {
  return {
    schemaVersion: 1,
    state: 'disabled',
    enabled: false,
    sessionId: null,
    turnId: null,
    lastError: { code: 'assistant_unavailable', message, recoverable: true },
    componentLatencyMs: {},
    receivedAt: new Date().toISOString(),
  }
}

export async function fetchVoiceStatus(baseUrl = ''): Promise<VoiceStatus> {
  const response = await fetch(`${baseUrl}/api/v1/voice/status`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`voice status request failed (${response.status})`)
  return parseVoiceStatus(await response.json() as unknown)
}

export function voiceStateLabel(status: VoiceStatus): string {
  const labels: Record<VoiceStatus['state'], string> = {
    disabled: '未启用',
    wake_listening: '等待唤醒',
    capturing: '收音中',
    processing_asr: '识别中',
    processing_assistant: '助手处理中',
    speaking: '播报中',
    audio_unavailable: '音频不可用',
    asr_error: '识别错误',
    assistant_unavailable: '助手不可用',
    tts_error: 'TTS 错误',
  }
  return labels[status.state]
}
