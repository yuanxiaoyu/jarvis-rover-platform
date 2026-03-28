import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

import type { LidarPoint, RuntimeState, VirtualWall, WorldModel } from '@/types/contract'

interface RoverSceneOptions {
  onZoneSelect?: (zoneId: string) => void
}

interface ZoneVisual {
  mesh: THREE.Mesh<THREE.ExtrudeGeometry, THREE.MeshStandardMaterial>
  color: THREE.Color
  opacity: number
}

const CATEGORY_COLORS: Record<string, string> = {
  lane: '#5f7f72',
  room: '#c7c29a',
  dock: '#587f8f',
  charging: '#d2a65f',
  inspection: '#8ea8d8',
  restricted: '#b96d61',
}

export class RoverScene {
  private readonly container: HTMLElement
  private readonly scene = new THREE.Scene()
  private readonly camera = new THREE.OrthographicCamera()
  private readonly renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  private readonly controls: OrbitControls
  private readonly raycaster = new THREE.Raycaster()
  private readonly pointer = new THREE.Vector2()
  private readonly worldGroup = new THREE.Group()
  private readonly overlaysGroup = new THREE.Group()
  private readonly zoneVisuals = new Map<string, ZoneVisual>()
  private readonly callbacks: RoverSceneOptions
  private readonly robot = new THREE.Group()
  private readonly lidarGeometry = new THREE.BufferGeometry()
  private readonly lidarMaterial = new THREE.PointsMaterial({
    size: 0.1,
    transparent: true,
    opacity: 0.7,
    color: '#7cf0df',
    sizeAttenuation: true,
  })
  private readonly lidarPoints = new THREE.Points(this.lidarGeometry, this.lidarMaterial)
  private readonly pathMaterial = new THREE.LineBasicMaterial({ color: '#f7d779' })
  private readonly pathGeometry = new THREE.BufferGeometry()
  private readonly pathLine = new THREE.Line(this.pathGeometry, this.pathMaterial)
  private animationFrameId = 0
  private resizeObserver?: ResizeObserver
  private currentWorld?: WorldModel
  private selectedZoneId: string | null = null
  private pointerDownAt = { x: 0, y: 0 }

  constructor(container: HTMLElement, options: RoverSceneOptions = {}) {
    this.container = container
    this.callbacks = options
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)

    this.setupScene()
    this.buildRobot()
    this.scene.add(this.worldGroup)
    this.scene.add(this.overlaysGroup)
    this.overlaysGroup.add(this.pathLine, this.lidarPoints, this.robot)
    this.bindEvents()
    this.onResize()
    this.animate()
  }

  destroy(): void {
    cancelAnimationFrame(this.animationFrameId)
    this.resizeObserver?.disconnect()
    this.controls.dispose()
    this.renderer.domElement.removeEventListener('pointerdown', this.handlePointerDown)
    this.renderer.domElement.removeEventListener('pointerup', this.handlePointerUp)
    this.renderer.domElement.removeEventListener('pointermove', this.handlePointerMove)
    this.renderer.dispose()
    this.disposeWorld()
  }

  setWorld(world: WorldModel): void {
    this.currentWorld = world
    this.disposeWorld()
    this.buildFloor(world)
    this.buildZones(world)
    this.buildVirtualWalls(world.virtualWalls)
    this.fitCamera(world)
  }

  setRuntime(runtime: RuntimeState): void {
    this.selectedZoneId = runtime.selectedZoneId
    this.robot.position.set(runtime.robotPose.x, 0.38, -runtime.robotPose.y)
    this.robot.rotation.y = -runtime.robotPose.yawRad
    this.updatePath(runtime.path.waypoints)
    this.updateLidar(runtime.lidar.points)
    this.syncZoneState()
  }

  private setupScene(): void {
    this.scene.background = new THREE.Color('#102326')
    this.scene.fog = new THREE.Fog('#102326', 10, 40)

    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight)
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.renderer.domElement.style.display = 'block'
    this.renderer.domElement.style.touchAction = 'none'
    this.container.appendChild(this.renderer.domElement)

    this.camera.near = 0.1
    this.camera.far = 100
    this.camera.position.set(12, 14, 12)
    this.camera.lookAt(6, 0, -5)

    this.controls.enableDamping = true
    this.controls.enablePan = true
    this.controls.minZoom = 0.7
    this.controls.maxZoom = 3.4
    this.controls.target.set(6, 0, -5)
    this.controls.update()

    const hemi = new THREE.HemisphereLight('#f0f7ef', '#113339', 1.25)
    const dir = new THREE.DirectionalLight('#fff7da', 1.3)
    dir.position.set(8, 16, 6)
    dir.castShadow = false
    this.scene.add(hemi, dir)
  }

  private buildFloor(world: WorldModel): void {
    const [minX, minY] = world.bounds.min
    const [maxX, maxY] = world.bounds.max
    const width = maxX - minX + 3
    const depth = maxY - minY + 3

    const base = new THREE.Mesh(
      new THREE.BoxGeometry(width, 0.25, depth),
      new THREE.MeshStandardMaterial({
        color: '#11282d',
        roughness: 0.9,
        metalness: 0.08,
      }),
    )

    base.position.set((minX + maxX) / 2, -0.16, -(minY + maxY) / 2)
    this.worldGroup.add(base)

    const grid = new THREE.GridHelper(Math.max(width, depth), Math.round(Math.max(width, depth) * 2), '#5fd7c4', '#244349')
    grid.position.set((minX + maxX) / 2, 0.01, -(minY + maxY) / 2)
    this.worldGroup.add(grid)
  }

  private buildZones(world: WorldModel): void {
    for (const zone of world.zones) {
      const shape = new THREE.Shape()
      zone.polygon.forEach(([x, y], index) => {
        if (index === 0) {
          shape.moveTo(x, y)
          return
        }

        shape.lineTo(x, y)
      })

      const height = zone.category === 'restricted' ? 1.2 : zone.category === 'lane' ? 0.38 : 0.72
      const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: height,
        bevelEnabled: false,
      })
      geometry.rotateX(-Math.PI / 2)

      const material = new THREE.MeshStandardMaterial({
        color: CATEGORY_COLORS[zone.category] ?? '#8a9a92',
        transparent: true,
        opacity: zone.selectable ? 0.88 : 0.42,
        roughness: 0.52,
        metalness: 0.18,
      })

      const mesh = new THREE.Mesh(geometry, material)
      mesh.userData.zoneId = zone.id
      this.worldGroup.add(mesh)
      this.zoneVisuals.set(zone.id, {
        mesh,
        color: material.color.clone(),
        opacity: material.opacity,
      })
    }
  }

  private buildVirtualWalls(walls: VirtualWall[]): void {
    for (const wall of walls) {
      const points = [
        new THREE.Vector3(wall.start[0], wall.height, -wall.start[1]),
        new THREE.Vector3(wall.end[0], wall.height, -wall.end[1]),
      ]
      const material = new THREE.LineBasicMaterial({
        color: wall.enabled ? '#ffd479' : '#6d8482',
        linewidth: 2,
      })
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material)
      this.worldGroup.add(line)

      const column = new THREE.Mesh(
        new THREE.CylinderGeometry(0.04, 0.04, wall.height, 12),
        new THREE.MeshStandardMaterial({
          color: wall.enabled ? '#ffd479' : '#60706f',
          emissive: wall.enabled ? '#805620' : '#000000',
        }),
      )

      column.position.set((wall.start[0] + wall.end[0]) / 2, wall.height / 2, -(wall.start[1] + wall.end[1]) / 2)
      this.worldGroup.add(column)
    }
  }

  private buildRobot(): void {
    const chassis = new THREE.Mesh(
      new THREE.CylinderGeometry(0.34, 0.42, 0.22, 24),
      new THREE.MeshStandardMaterial({
        color: '#e0f8ef',
        metalness: 0.18,
        roughness: 0.45,
      }),
    )
    chassis.rotation.z = Math.PI / 2

    const nose = new THREE.Mesh(
      new THREE.ConeGeometry(0.2, 0.5, 24),
      new THREE.MeshStandardMaterial({
        color: '#ffbf71',
        emissive: '#643f12',
        emissiveIntensity: 0.4,
      }),
    )
    nose.position.set(0.44, 0.04, 0)
    nose.rotation.z = -Math.PI / 2

    const sweep = new THREE.Mesh(
      new THREE.CircleGeometry(1.4, 48, -Math.PI / 7, Math.PI / 3.5),
      new THREE.MeshBasicMaterial({
        color: '#73eed8',
        transparent: true,
        opacity: 0.12,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    )
    sweep.rotation.x = -Math.PI / 2
    sweep.position.y = 0.02

    this.robot.add(chassis, nose, sweep)
  }

  private updatePath(points: Array<[number, number]>): void {
    if (points.length < 2) {
      this.pathGeometry.setAttribute('position', new THREE.Float32BufferAttribute([], 3))
      return
    }

    const vertices = points.flatMap(([x, y]) => [x, 0.24, -y])
    this.pathGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
    this.pathGeometry.computeBoundingSphere()
  }

  private updateLidar(points: LidarPoint[]): void {
    const vertices = points.flatMap((point) => [point.x, 0.14 + point.intensity * 0.1, -point.y])
    this.lidarGeometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
    this.lidarGeometry.computeBoundingSphere()
  }

  private fitCamera(world: WorldModel): void {
    const aspect = Math.max(this.container.clientWidth / Math.max(this.container.clientHeight, 1), 1)
    const [minX, minY] = world.bounds.min
    const [maxX, maxY] = world.bounds.max
    const width = maxX - minX
    const depth = maxY - minY
    const span = Math.max(width, depth) * 0.72 + 2
    const centerX = (minX + maxX) / 2
    const centerZ = -(minY + maxY) / 2

    this.camera.left = -span * aspect
    this.camera.right = span * aspect
    this.camera.top = span
    this.camera.bottom = -span
    this.camera.position.set(centerX + span * 0.65, span * 1.28, centerZ + span * 0.55)
    this.camera.lookAt(centerX, 0, centerZ)
    this.camera.updateProjectionMatrix()

    this.controls.target.set(centerX, 0, centerZ)
    this.controls.update()
  }

  private syncZoneState(): void {
    for (const [zoneId, visual] of this.zoneVisuals) {
      const isSelected = zoneId === this.selectedZoneId
      visual.mesh.material.color.copy(visual.color)
      visual.mesh.material.emissive.set(isSelected ? '#ffffff' : '#000000')
      visual.mesh.material.emissiveIntensity = isSelected ? 0.22 : 0
      visual.mesh.material.opacity = isSelected ? 1 : visual.opacity
    }
  }

  private disposeWorld(): void {
    for (const child of [...this.worldGroup.children]) {
      this.worldGroup.remove(child)
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose())
        } else {
          child.material.dispose()
        }
      }

      if (child instanceof THREE.Line) {
        child.geometry.dispose()
        child.material.dispose()
      }
    }

    this.zoneVisuals.clear()
  }

  private onResize(): void {
    const width = this.container.clientWidth
    const height = this.container.clientHeight
    this.renderer.setSize(width, height)
    if (this.currentWorld) {
      this.fitCamera(this.currentWorld)
    }
  }

  private bindEvents(): void {
    this.resizeObserver = new ResizeObserver(() => this.onResize())
    this.resizeObserver.observe(this.container)

    this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown)
    this.renderer.domElement.addEventListener('pointerup', this.handlePointerUp)
    this.renderer.domElement.addEventListener('pointermove', this.handlePointerMove)
  }

  private animate = (): void => {
    this.animationFrameId = requestAnimationFrame(this.animate)
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  private handlePointerDown = (event: PointerEvent): void => {
    this.pointerDownAt = { x: event.clientX, y: event.clientY }
  }

  private handlePointerMove = (event: PointerEvent): void => {
    if (!this.container) {
      return
    }

    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
  }

  private handlePointerUp = (event: PointerEvent): void => {
    const deltaX = Math.abs(event.clientX - this.pointerDownAt.x)
    const deltaY = Math.abs(event.clientY - this.pointerDownAt.y)

    if (deltaX > 5 || deltaY > 5) {
      return
    }

    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const meshes = [...this.zoneVisuals.values()].map((visual) => visual.mesh)
    const hit = this.raycaster.intersectObjects(meshes, false)[0]

    const zoneId = hit?.object.userData.zoneId
    if (typeof zoneId === 'string') {
      this.callbacks.onZoneSelect?.(zoneId)
    }
  }
}
