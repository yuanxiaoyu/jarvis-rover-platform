import type { VoiceStatus } from '@/types/contract'

export async function fetchVoiceStatus(baseUrl = ''): Promise<VoiceStatus> {
  const response = await fetch(`${baseUrl}/api/v1/voice/status`)
  if (!response.ok) throw new Error(`voice status ${response.status}`)
  return (await response.json()) as VoiceStatus
}
