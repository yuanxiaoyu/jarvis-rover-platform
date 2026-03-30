import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'

import type { RuntimeState, Vec2, VirtualWall, WorldModel } from '@/types/contract'

interface RoverSceneOptions {
  onZoneSelect?: (zoneId: string) => void
  onZoneDoubleClick?: (zoneId: string) => void
  onMapPrimaryAction?: (point: Vec2) => void
  onMapSecondaryAction?: (point: Vec2) => void
  onMapHover?: (point: Vec2 | null) => void
}

interface ZonePalette {
  top: THREE.Color
  topHover: THREE.Color
  topCurrent: THREE.Color
  side: THREE.Color
  sideHover: THREE.Color
  sideCurrent: THREE.Color
  cap: THREE.Color
  capHover: THREE.Color
  capCurrent: THREE.Color
  outline: THREE.Color
}

interface ZoneVisual {
  mesh: THREE.Mesh<THREE.ExtrudeGeometry, THREE.MeshStandardMaterial[]>
  topMaterial: THREE.MeshStandardMaterial
  sideMaterial: THREE.MeshStandardMaterial
  floor: THREE.Mesh<THREE.ShapeGeometry, THREE.MeshStandardMaterial>
  floorMaterial: THREE.MeshStandardMaterial
  floorGrid: THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial>
  shadow: THREE.Mesh<THREE.ShapeGeometry, THREE.MeshBasicMaterial>
  outline: THREE.LineLoop<THREE.BufferGeometry, THREE.LineBasicMaterial>
  edges: THREE.LineSegments<THREE.EdgesGeometry, THREE.LineBasicMaterial>
  label: CSS2DObject
  labelElement: HTMLDivElement
  palette: ZonePalette
  height: number
}

const CATEGORY_COLORS: Record<string, string> = {
  lane: '#f3f5f4',
  room: '#f6f7f6',
  dock: '#eef4f6',
  charging: '#f6f2ea',
  inspection: '#eef2f8',
  restricted: '#f5eded',
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
  private readonly labelRenderer = new CSS2DRenderer()
  private readonly controls: OrbitControls
  private readonly raycaster = new THREE.Raycaster()
  private readonly pointer = new THREE.Vector2()
  private readonly groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  private readonly worldGroup = new THREE.Group()
  private readonly routeDots = new THREE.Group()
  private readonly waypointDots = new THREE.Group()
  private readonly robot = new THREE.Group()
  private readonly pulseRing = new THREE.Mesh(
    new THREE.RingGeometry(0.32, 0.44, 48),
    new THREE.MeshBasicMaterial({
      color: '#f1ffff',
      transparent: true,
      opacity: 0.65,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  )
  private readonly sensorSweep = new THREE.Mesh(
    new THREE.CircleGeometry(0.92, 64, 0, Math.PI / 3),
    new THREE.MeshBasicMaterial({
      color: '#6fd3be',
      transparent: true,
      opacity: 0.18,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  )
  private readonly callbacks: RoverSceneOptions
  private readonly zoneVisuals = new Map<string, ZoneVisual>()
  private readonly wallObjects: THREE.Object3D[] = []
  private resizeObserver?: ResizeObserver
  private routeMesh?: THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>
  private draftWallLine?: THREE.Line<THREE.BufferGeometry, THREE.LineDashedMaterial>
  private currentWorld?: WorldModel
  private selectedZoneId: string | null = null
  private hoveredZoneId: string | null = null
  private pointerDownAt = { x: 0, y: 0 }
  private houseCenter = new THREE.Vector3(8, 0, 6)
  private routeHeight = 1.02

  constructor(container: HTMLElement, options: RoverSceneOptions = {}) {
    this.container = container
    this.callbacks = options
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)

    this.setupScene()
    this.buildRobot()
    this.scene.add(this.worldGroup, this.routeDots, this.waypointDots, this.robot)
    this.bindInteractions()
    this.render()
  }

  destroy(): void {
    this.resizeObserver?.disconnect()
    this.controls.dispose()
    this.renderer.domElement.removeEventListener('pointerdown', this.handlePointerDown)
    this.renderer.domElement.removeEventListener('pointermove', this.handlePointerMove)
    this.renderer.domElement.removeEventListener('pointerup', this.handlePointerUp)
    this.renderer.domElement.removeEventListener('pointerleave', this.handlePointerLeave)
    this.renderer.domElement.removeEventListener('contextmenu', this.handleContextMenu)
    this.renderer.domElement.removeEventListener('dblclick', this.handleDoubleClick)
    this.clearRoute()
    this.disposeWorld()
    this.renderer.dispose()
    this.labelRenderer.domElement.remove()
  }

  setWorld(world: WorldModel): void {
    this.currentWorld = world
    this.disposeWorld()
    this.houseCenter = new THREE.Vector3(
      (world.bounds.min[0] + world.bounds.max[0]) / 2,
      0,
      (world.bounds.min[1] + world.bounds.max[1]) / 2,
    )

    this.buildEnvironment(world)
    this.buildHousePlate(world)
    if (world.mapping.status === 'ready') {
      this.buildZones(world)
      this.buildVirtualWalls(world.virtualWalls)
    }
    this.onResize()
    this.syncZoneState()
    this.render()
  }

  setRuntime(runtime: RuntimeState): void {
    this.selectedZoneId = runtime.selectedZoneId
    this.robot.position.set(runtime.robotPose.x, this.routeHeight, runtime.robotPose.y)
    this.robot.rotation.y = -runtime.robotPose.yawRad
    this.showRoute(runtime.path.waypoints)
    this.syncZoneState()
    this.render()
  }

  setDraftWall(draft: { start: Vec2; end: Vec2 | null } | null): void {
    if (!draft?.start || !draft.end) {
      if (this.draftWallLine) {
        this.scene.remove(this.draftWallLine)
        this.draftWallLine.geometry.dispose()
        this.draftWallLine.material.dispose()
        this.draftWallLine = undefined
        this.render()
      }
      return
    }

    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(draft.start[0], 0.82, draft.start[1]),
      new THREE.Vector3(draft.end[0], 0.82, draft.end[1]),
    ])

    if (!this.draftWallLine) {
      this.draftWallLine = new THREE.Line(
        geometry,
        new THREE.LineDashedMaterial({
          color: '#2c9f88',
          dashSize: 0.28,
          gapSize: 0.18,
          transparent: true,
          opacity: 0.92,
        }),
      )
      this.scene.add(this.draftWallLine)
    } else {
      this.draftWallLine.geometry.dispose()
      this.draftWallLine.geometry = geometry
    }

    this.draftWallLine.computeLineDistances()
    this.render()
  }

  setWaypointDraft(points: Vec2[]): void {
    for (const child of [...this.waypointDots.children]) {
      this.waypointDots.remove(child)
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose())
        } else {
          child.material.dispose()
        }
      }
    }

    points.forEach((point, index) => {
      const marker = new THREE.Mesh(
        new THREE.CylinderGeometry(0.14, 0.14, 0.08, 20),
        new THREE.MeshBasicMaterial({
          color: index === points.length - 1 ? '#73ffd8' : '#fff7ea',
          transparent: true,
          opacity: 0.96,
        }),
      )
      marker.position.set(point[0], this.routeHeight - 0.12, point[1])
      this.waypointDots.add(marker)
    })

    this.render()
  }

  private setupScene(): void {
    this.scene.background = null
    this.scene.fog = null

    this.camera.position.set(this.houseCenter.x, 20, this.houseCenter.z)
    this.camera.up.set(0, 0, -1)
    this.camera.lookAt(this.houseCenter)
    this.camera.zoom = 1.18
    this.camera.near = 0.1
    this.camera.far = 100
    this.camera.updateProjectionMatrix()

    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.2))
    this.renderer.shadowMap.enabled = false
    this.renderer.domElement.style.display = 'block'
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.renderer.domElement.style.touchAction = 'none'

    this.labelRenderer.domElement.style.position = 'absolute'
    this.labelRenderer.domElement.style.inset = '0'
    this.labelRenderer.domElement.style.pointerEvents = 'none'

    this.container.append(this.renderer.domElement, this.labelRenderer.domElement)

    this.controls.enableRotate = false
    this.controls.enablePan = false
    this.controls.enableDamping = false
    this.controls.screenSpacePanning = true
    this.controls.minZoom = 0.9
    this.controls.maxZoom = 2.4
    this.controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE
    this.controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY
    this.controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE
    this.controls.target.copy(this.houseCenter)
    this.controls.update()
    this.controls.addEventListener('change', this.render)

    const ambientLight = new THREE.AmbientLight('#d8f5ef', 1.15)
    const keyLight = new THREE.DirectionalLight('#f7fff6', 1.15)
    const fillLight = new THREE.DirectionalLight('#7eb6cb', 0.36)
    const rimLight = new THREE.DirectionalLight('#7fe1c6', 0.22)

    keyLight.position.set(14, 20, 3)
    fillLight.position.set(-16, 11, 16)
    rimLight.position.set(4, 8, 18)

    this.scene.add(ambientLight, keyLight, fillLight, rimLight)
  }

  private buildEnvironment(world: WorldModel): void {
    const span = Math.max(world.bounds.max[0] - world.bounds.min[0], world.bounds.max[1] - world.bounds.min[1]) + 8

    const grid = new THREE.GridHelper(span, Math.round(span / 1.5), '#284047', '#16262b')
    grid.position.y = -0.48
    if (Array.isArray(grid.material)) {
      grid.material.forEach((material) => {
        material.transparent = true
        material.opacity = 0.24
      })
    } else {
      grid.material.transparent = true
      grid.material.opacity = 0.24
    }

    this.worldGroup.add(grid)
  }

  private buildHousePlate(world: WorldModel): void {
    const outerShape = createShape([
      [world.bounds.min[0] - 0.4, world.bounds.min[1] - 0.4],
      [world.bounds.max[0] + 0.4, world.bounds.min[1] - 0.4],
      [world.bounds.max[0] + 0.4, world.bounds.max[1] + 0.4],
      [world.bounds.min[0] - 0.4, world.bounds.max[1] + 0.4],
    ])

    const baseGeometry = new THREE.ExtrudeGeometry(outerShape, {
      depth: 0.4,
      bevelEnabled: false,
    })
    baseGeometry.rotateX(-Math.PI / 2)

    const baseMesh = new THREE.Mesh(
      baseGeometry,
      [
        new THREE.MeshStandardMaterial({
          color: '#16262b',
          roughness: 0.92,
          metalness: 0.02,
        }),
        new THREE.MeshStandardMaterial({
          color: '#0d1a1e',
          roughness: 0.92,
          metalness: 0.01,
        }),
      ],
    )

    baseMesh.position.y = -0.42
    baseMesh.receiveShadow = true
    this.worldGroup.add(baseMesh)

    const borderGeometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(world.bounds.min[0] - 0.4, -0.01, world.bounds.min[1] - 0.4),
      new THREE.Vector3(world.bounds.max[0] + 0.4, -0.01, world.bounds.min[1] - 0.4),
      new THREE.Vector3(world.bounds.max[0] + 0.4, -0.01, world.bounds.max[1] + 0.4),
      new THREE.Vector3(world.bounds.min[0] - 0.4, -0.01, world.bounds.max[1] + 0.4),
    ])

    const border = new THREE.LineLoop(
      borderGeometry,
      new THREE.LineBasicMaterial({
        color: '#95a6a0',
        transparent: true,
        opacity: 0.24,
      }),
    )

    border.position.y = 0.03
    this.worldGroup.add(border)
  }

  private buildZones(world: WorldModel): void {
    for (const zone of world.zones) {
      const visual = this.createZoneVisual(zone, world)
      this.zoneVisuals.set(zone.id, visual)
      this.worldGroup.add(visual.shadow, visual.mesh, visual.floor, visual.floorGrid, visual.outline, visual.edges, visual.label)
    }
  }

  private createZoneVisual(zone: WorldModel['zones'][number], world: WorldModel): ZoneVisual {
    const shape = createShape(zone.polygon)
    const zoneHeight = getZoneHeight(zone.category)

    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: zoneHeight,
      bevelEnabled: true,
      bevelSegments: 2,
      steps: 1,
      bevelSize: 0.03,
      bevelThickness: 0.03,
    })
    geometry.rotateX(-Math.PI / 2)

    const baseColor = new THREE.Color(CATEGORY_COLORS[zone.category] ?? '#a9c8b2')
    const palette = createZonePalette(baseColor)
    const topMaterial = new THREE.MeshStandardMaterial({
      color: palette.top,
      roughness: 0.9,
      metalness: 0,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    })
    const sideMaterial = new THREE.MeshStandardMaterial({
      color: new THREE.Color('#f5f7f6'),
      roughness: 0.92,
      metalness: 0,
    })

    const mesh = new THREE.Mesh(geometry, [topMaterial, sideMaterial])
    mesh.userData.zoneId = zone.id
    mesh.position.y = 0
    mesh.castShadow = true
    mesh.receiveShadow = true

    const center = getPolygonCenter(zone.polygon)
    const capGeometry = new THREE.ShapeGeometry(shape)
    capGeometry.rotateX(-Math.PI / 2)

    const floorMaterial = new THREE.MeshStandardMaterial({
      color: new THREE.Color('#f5f7f6'),
      roughness: 0.58,
      metalness: 0,
    })
    const floor = new THREE.Mesh(capGeometry, floorMaterial)
    floor.position.y = 0.04
    floor.receiveShadow = true

    const floorGrid = createFloorGrid(zone.polygon)
    floorGrid.position.y = 0.055

    const shadowGeometry = new THREE.ShapeGeometry(shape)
    shadowGeometry.rotateX(-Math.PI / 2)
    const shadow = new THREE.Mesh(
      shadowGeometry,
      new THREE.MeshBasicMaterial({
      color: '#000000',
      transparent: true,
      opacity: 0.12,
      depthWrite: false,
    }),
    )
    shadow.position.set(0.18, 0.02, 0.22)
    shadow.scale.set(1.06, 1, 1.05)

    const outlineGeometry = new THREE.BufferGeometry().setFromPoints(
      zone.polygon.map(([x, y]) => new THREE.Vector3(x, zoneHeight + 0.03, y)),
    )
    const outline = new THREE.LineLoop(
      outlineGeometry,
      new THREE.LineBasicMaterial({
        color: palette.outline,
        transparent: true,
        opacity: 0.42,
      }),
    )

    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 18),
      new THREE.LineBasicMaterial({
        color: palette.outline,
        transparent: true,
        opacity: 0.2,
      }),
    )

    const labelModel = [...world.regionLabels].reverse().find((item) => item.zoneId === zone.id)
    const labelName = labelModel?.name ?? ''
    const labelElement = document.createElement('div')
    labelElement.className = labelModel ? 'map-label' : 'map-label is-hidden'
    labelElement.innerHTML = `
      <span class="map-label__name">${labelName}</span>
      <span class="map-label__meta">${labelModel ? zone.category : ''}</span>
    `

    const label = new CSS2DObject(labelElement)
    const anchor = labelModel?.position ?? zone.labelAnchor ?? center
    label.position.set(anchor[0], zoneHeight + 0.12, anchor[1])

    return {
      mesh,
      topMaterial,
      sideMaterial,
      floor,
      floorMaterial,
      floorGrid,
      shadow,
      outline,
      edges,
      label,
      labelElement,
      palette,
      height: zoneHeight,
    }
  }

  private buildVirtualWalls(walls: VirtualWall[]): void {
    for (const wall of walls) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(wall.start[0], 0.84, wall.start[1]),
          new THREE.Vector3(wall.end[0], 0.84, wall.end[1]),
        ]),
        new THREE.LineBasicMaterial({
          color: wall.enabled ? '#ffbf6d' : '#8ca09a',
          transparent: true,
          opacity: wall.enabled ? 0.96 : 0.48,
        }),
      )

      const waypoint = new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.12, 0.08, 24),
        new THREE.MeshBasicMaterial({
          color: wall.enabled ? '#fff7ea' : '#d0d7d4',
          transparent: true,
          opacity: 0.92,
        }),
      )

      waypoint.position.set((wall.start[0] + wall.end[0]) / 2, 0.8, (wall.start[1] + wall.end[1]) / 2)
      this.worldGroup.add(line, waypoint)
      this.wallObjects.push(line, waypoint)
    }
  }

  private buildRobot(): void {
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.26, 0.26, 0.16, 40),
      new THREE.MeshStandardMaterial({
        color: '#f7fffd',
        roughness: 0.3,
        metalness: 0.12,
        emissive: '#2fb49a',
        emissiveIntensity: 0.28,
      }),
    )

    const inner = new THREE.Mesh(
      new THREE.CylinderGeometry(0.12, 0.12, 0.2, 24),
      new THREE.MeshBasicMaterial({
        color: '#73ffd8',
        transparent: true,
        opacity: 0.92,
      }),
    )

    const heading = new THREE.Mesh(
      new THREE.ConeGeometry(0.16, 0.42, 3),
      new THREE.MeshStandardMaterial({
        color: '#10312b',
        roughness: 0.32,
        metalness: 0.08,
      }),
    )

    heading.rotation.x = Math.PI / 2
    heading.position.set(0, 0.18, 0.26)

    this.pulseRing.rotation.x = -Math.PI / 2
    this.pulseRing.position.y = 0.02

    this.sensorSweep.rotation.x = -Math.PI / 2
    this.sensorSweep.position.y = 0.025

    base.position.y = 0.12
    inner.position.y = 0.16
    this.robot.add(this.sensorSweep, this.pulseRing, base, inner, heading)
  }

  private bindInteractions(): void {
    this.resizeObserver = new ResizeObserver(() => this.onResize())
    this.resizeObserver.observe(this.container)

    this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown)
    this.renderer.domElement.addEventListener('pointermove', this.handlePointerMove)
    this.renderer.domElement.addEventListener('pointerup', this.handlePointerUp)
    this.renderer.domElement.addEventListener('pointerleave', this.handlePointerLeave)
    this.renderer.domElement.addEventListener('contextmenu', this.handleContextMenu)
    this.renderer.domElement.addEventListener('dblclick', this.handleDoubleClick)
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.pointerDownAt = { x: event.clientX, y: event.clientY }
  }

  private readonly handlePointerMove = (event: PointerEvent): void => {
    const point = this.projectPoint(event)
    this.callbacks.onMapHover?.(point)

    const zoneId = this.pickZone(event)
    if (zoneId === this.hoveredZoneId) {
      return
    }

    this.hoveredZoneId = zoneId
    this.syncZoneState()
    this.render()
  }

  private readonly handlePointerUp = (event: PointerEvent): void => {
    if (event.button !== 0) {
      return
    }

    const movement = Math.hypot(event.clientX - this.pointerDownAt.x, event.clientY - this.pointerDownAt.y)
    if (movement > 5) {
      return
    }

    const point = this.projectPoint(event)
    if (point) {
      this.callbacks.onMapPrimaryAction?.(point)
    }

    const zoneId = this.pickZone(event)
    if (zoneId) {
      this.callbacks.onZoneSelect?.(zoneId)
    }
  }

  private readonly handlePointerLeave = (): void => {
    this.hoveredZoneId = null
    this.callbacks.onMapHover?.(null)
    this.syncZoneState()
    this.render()
  }

  private readonly handleContextMenu = (event: MouseEvent): void => {
    event.preventDefault()
    const point = this.projectPoint(event)
    if (point) {
      this.callbacks.onMapSecondaryAction?.(point)
    }
  }

  private readonly handleDoubleClick = (event: MouseEvent): void => {
    const zoneId = this.pickZone(event)
    if (zoneId) {
      this.callbacks.onZoneDoubleClick?.(zoneId)
    }
  }

  private pickZone(event: PointerEvent | MouseEvent): string | null {
    const bounds = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
    this.pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.camera)

    const intersections = this.raycaster.intersectObjects(
      Array.from(this.zoneVisuals.values()).map((visual) => visual.mesh),
      false,
    )

    if (intersections.length === 0) {
      return null
    }

    return intersections[0].object.userData.zoneId ?? null
  }

  private projectPoint(event: PointerEvent | MouseEvent): Vec2 | null {
    const bounds = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
    this.pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.camera)

    const hit = new THREE.Vector3()
    const found = this.raycaster.ray.intersectPlane(this.groundPlane, hit)
    if (!found || !this.currentWorld) {
      return null
    }

    return [
      Math.min(this.currentWorld.bounds.max[0], Math.max(this.currentWorld.bounds.min[0], hit.x)),
      Math.min(this.currentWorld.bounds.max[1], Math.max(this.currentWorld.bounds.min[1], hit.z)),
    ]
  }

  private onResize(): void {
    const width = Math.max(this.container.clientWidth, 1)
    const height = Math.max(this.container.clientHeight, 1)
    const aspect = width / height
    const world = this.currentWorld
    const worldWidth = (world?.bounds.max[0] ?? 16) - (world?.bounds.min[0] ?? 0)
    const worldHeight = (world?.bounds.max[1] ?? 12) - (world?.bounds.min[1] ?? 0)
    const paddedWidth = worldWidth + 5.5
    const paddedHeight = worldHeight + 5.5

    let halfWidth = paddedWidth / 2
    let halfHeight = paddedHeight / 2

    if (paddedWidth / paddedHeight > aspect) {
      halfHeight = halfWidth / aspect
    } else {
      halfWidth = halfHeight * aspect
    }

    this.camera.left = -halfWidth
    this.camera.right = halfWidth
    this.camera.top = halfHeight
    this.camera.bottom = -halfHeight
    this.camera.updateProjectionMatrix()

    this.camera.position.set(this.houseCenter.x, 20, this.houseCenter.z)
    this.camera.lookAt(this.houseCenter)
    this.controls.target.copy(this.houseCenter)
    this.controls.update()

    this.renderer.setSize(width, height, false)
    this.labelRenderer.setSize(width, height)
    this.render()
  }

  private render = (): void => {
    this.renderer.render(this.scene, this.camera)
    this.labelRenderer.render(this.scene, this.camera)
  }

  private syncZoneState(): void {
    for (const [zoneId, visual] of this.zoneVisuals) {
      const isCurrent = zoneId === this.selectedZoneId
      const isHovered = zoneId === this.hoveredZoneId

      const topColor = isCurrent
        ? visual.palette.topCurrent
        : isHovered
          ? visual.palette.topHover
          : visual.palette.top
      const sideColor = isCurrent
        ? visual.palette.sideCurrent
        : isHovered
          ? visual.palette.sideHover
          : visual.palette.side
      const capColor = isCurrent
        ? visual.palette.capCurrent
        : isHovered
          ? visual.palette.capHover
          : visual.palette.cap
      const lift = isCurrent ? 0.03 : isHovered ? 0.015 : 0

      visual.topMaterial.color.copy(topColor)
      visual.topMaterial.emissive.set(isCurrent ? '#53bca5' : isHovered ? '#ffffff' : '#000000')
      visual.topMaterial.emissiveIntensity = isCurrent ? 0.16 : isHovered ? 0.06 : 0
      visual.sideMaterial.color.copy(sideColor)
      visual.floorMaterial.color.copy(capColor)
      visual.mesh.position.y = lift
      visual.floor.position.y = 0.04 + lift * 0.2
      visual.floorGrid.position.y = 0.055 + lift * 0.2
      visual.outline.position.y = lift
      visual.edges.position.y = lift
      visual.label.position.y = visual.height + 0.12 + lift
      ;(visual.shadow.material as THREE.MeshBasicMaterial).opacity = isCurrent ? 0.16 : isHovered ? 0.12 : 0.1
      visual.outline.material.opacity = isCurrent ? 0.72 : isHovered ? 0.5 : 0.42
      visual.edges.material.opacity = isCurrent ? 0.34 : isHovered ? 0.24 : 0.2

      visual.labelElement.classList.toggle('is-current', isCurrent)
      visual.labelElement.classList.toggle('is-hovered', isHovered)
    }
    this.render()
  }

  private showRoute(points: Vec2[]): void {
    this.clearRoute()
    if (points.length < 2) {
      return
    }

    const worldPoints = points.map(([x, y]) => new THREE.Vector3(x, this.routeHeight, y))
    const geometry = new THREE.BufferGeometry().setFromPoints(worldPoints)
    const material = new THREE.LineBasicMaterial({
      color: '#ffbf6d',
      transparent: true,
      opacity: 0.95,
    })

    this.routeMesh = new THREE.Line(geometry, material)
    this.scene.add(this.routeMesh)

    for (const point of worldPoints) {
      const waypoint = new THREE.Mesh(
        new THREE.CylinderGeometry(0.14, 0.14, 0.06, 24),
        new THREE.MeshBasicMaterial({
          color: '#fff7ea',
          transparent: true,
          opacity: 0.92,
        }),
      )

      waypoint.position.copy(point)
      waypoint.position.y = this.routeHeight - 0.12
      this.routeDots.add(waypoint)
    }
    this.render()
  }

  private clearRoute(): void {
    if (this.routeMesh) {
      this.routeMesh.geometry.dispose()
      this.routeMesh.material.dispose()
      this.scene.remove(this.routeMesh)
      this.routeMesh = undefined
    }

    for (const child of this.routeDots.children) {
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose())
        } else {
          child.material.dispose()
        }
      }
    }
    this.routeDots.clear()
  }

  private disposeWorld(): void {
    for (const visual of this.zoneVisuals.values()) {
      visual.mesh.geometry.dispose()
      visual.topMaterial.dispose()
      visual.sideMaterial.dispose()
      visual.floor.geometry.dispose()
      visual.floorMaterial.dispose()
      visual.floorGrid.geometry.dispose()
      visual.floorGrid.material.dispose()
      visual.shadow.geometry.dispose()
      visual.shadow.material.dispose()
      visual.outline.geometry.dispose()
      visual.outline.material.dispose()
      visual.edges.geometry.dispose()
      visual.edges.material.dispose()
      this.worldGroup.remove(visual.shadow, visual.mesh, visual.floor, visual.floorGrid, visual.outline, visual.edges, visual.label)
    }
    this.zoneVisuals.clear()

    for (const object of this.wallObjects) {
      this.worldGroup.remove(object)
      if (object instanceof THREE.Line || object instanceof THREE.Mesh) {
        object.geometry.dispose()
        if (Array.isArray(object.material)) {
          object.material.forEach((material) => material.dispose())
        } else {
          object.material.dispose()
        }
      }
    }
    this.wallObjects.length = 0

    for (const child of [...this.worldGroup.children]) {
      this.worldGroup.remove(child)
      if (child instanceof THREE.Mesh || child instanceof THREE.Line || child instanceof THREE.GridHelper) {
        child.geometry.dispose()
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose())
        } else {
          child.material.dispose()
        }
      }
    }
  }
}

function createZonePalette(color: THREE.Color): ZonePalette {
  return {
    top: color.clone(),
    topHover: color.clone().lerp(new THREE.Color('#ffffff'), 0.12),
    topCurrent: color.clone().lerp(new THREE.Color('#6fe2c2'), 0.22),
    side: color.clone().multiplyScalar(0.76),
    sideHover: color.clone().multiplyScalar(0.8),
    sideCurrent: color.clone().lerp(new THREE.Color('#318f7b'), 0.34).multiplyScalar(0.88),
    cap: color.clone().lerp(new THREE.Color('#ffffff'), 0.2),
    capHover: color.clone().lerp(new THREE.Color('#ffffff'), 0.3),
    capCurrent: color.clone().lerp(new THREE.Color('#dffff5'), 0.34),
    outline: color.clone().lerp(new THREE.Color('#32413c'), 0.5),
  }
}

function getZoneHeight(category: string): number {
  switch (category) {
    case 'lane':
      return 0.42
    case 'dock':
      return 0.48
    case 'charging':
      return 0.54
    case 'inspection':
      return 0.62
    case 'restricted':
      return 0.68
    case 'room':
    default:
      return 0.58
  }
}

function createShape(points: Vec2[]): THREE.Shape {
  const [startX, startZ] = points[0]
  const shape = new THREE.Shape()
  shape.moveTo(startX, -startZ)

  for (const [x, z] of points.slice(1)) {
    shape.lineTo(x, -z)
  }

  shape.closePath()
  return shape
}

function getPolygonCenter(points: Vec2[]): Vec2 {
  const total = points.reduce(
    (memo, point) => {
      memo.x += point[0]
      memo.y += point[1]
      return memo
    },
    { x: 0, y: 0 },
  )

  return [total.x / points.length, total.y / points.length]
}

function createFloorGrid(points: Vec2[]): THREE.LineSegments<THREE.BufferGeometry, THREE.LineBasicMaterial> {
  const xs = points.map(([x]) => x)
  const ys = points.map(([, y]) => y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const step = 0.8
  const inset = 0.08
  const vertices: number[] = []

  for (let x = minX + step; x < maxX - step / 2; x += step) {
    vertices.push(x, 0, minY + inset, x, 0, maxY - inset)
  }

  for (let y = minY + step; y < maxY - step / 2; y += step) {
    vertices.push(minX + inset, 0, y, maxX - inset, 0, y)
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))

  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({
      color: '#d2d8d5',
      transparent: true,
      opacity: 0.58,
    }),
  )
}
