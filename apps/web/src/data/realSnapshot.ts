import type { RoverSnapshot } from '@/types/contract'

/** Empty state used until the runtime APIs provide real telemetry. */
export function createInitialSnapshot(): RoverSnapshot {
  return {
    world: { mapId: '', mapName: '地图不可用', bounds: { min: [0, 0], max: [1, 1] }, zones: [], virtualWalls: [] },
    runtime: {
      robotPose: { x: 0, y: 0, yawRad: 0, linearVelocity: 0, angularVelocity: 0, frameId: '', stampMs: 0 },
      path: { id: '', status: 'idle', waypoints: [] },
      lidar: { frameId: '', stampMs: 0, maxRangeM: 0, points: [] },
      camera: { sourceId: '', title: '摄像头不可用', connected: false, frameUrl: '', width: 0, height: 0, fps: 0, latencyMs: 0 },
      telemetry: { batteryPercent: 0, cpuPercent: 0, temperatureC: 0, networkRttMs: 0, localizationConfidence: 0, motorCurrentA: 0 },
      mission: { mode: 'idle', objective: '等待真实 runtime 状态', statusLine: 'runtime 数据不可用' },
      tasks: [], voice: { listening: false, wakeWordArmed: false, transcript: '', confidence: 0 }, selectedZoneId: null,
    },
  }
}
