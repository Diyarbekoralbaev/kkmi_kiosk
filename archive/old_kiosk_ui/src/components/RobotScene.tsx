import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { useSession } from '../state/session'

interface Props {
  getAnalyser: () => AnalyserNode | null
}

const ROBOT_URL = '/models/robot.glb'

/**
 * Full-body 3D humanoid robot scene.
 * Universal loader: works with ANY GLB by auto-centering and auto-fitting
 * the camera to its bounding box. Static (no-animation) models are still
 * animated via subtle scene rotation and audio-driven head tilt.
 */
export function RobotScene({ getAnalyser }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const analyserGetterRef = useRef(getAnalyser)

  useEffect(() => {
    analyserGetterRef.current = getAnalyser
  }, [getAnalyser])

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    let disposed = false

    // ------- Renderer / Scene / Camera ----------------------------------
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 0.85

    const initW = Math.max(1, mount.clientWidth)
    const initH = Math.max(1, mount.clientHeight)
    renderer.setSize(initW, initH, false)
    // Force the canvas to fill its parent — without these styles the
    // WebGL canvas can end up at 0×0 inside a flex container.
    Object.assign(renderer.domElement.style, {
      display: 'block',
      width: '100%',
      height: '100%',
      position: 'absolute',
      inset: '0',
    })
    mount.appendChild(renderer.domElement)
    // eslint-disable-next-line no-console
    console.log('[RobotScene] mounted', { initW, initH })

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(35, initW / initH, 0.1, 200)

    // Default camera; will be repositioned after model loads
    camera.position.set(0, 1.6, 6)
    camera.lookAt(0, 1, 0)

    // ------- Lights ------------------------------------------------------
    scene.add(new THREE.HemisphereLight(0xa8d8ff, 0x081424, 0.6))

    const key = new THREE.DirectionalLight(0xffffff, 1.0)
    key.position.set(4, 6, 6)
    scene.add(key)

    const rimBlue = new THREE.DirectionalLight(0x40b0e0, 0.8)
    rimBlue.position.set(-5, 3, -3)
    scene.add(rimBlue)

    const rimCyan = new THREE.DirectionalLight(0x7ee3ff, 0.6)
    rimCyan.position.set(5, 1, -4)
    scene.add(rimCyan)

    // Audio-reactive chest glow point — sits inside the model and pulses
    // brightness with playback FFT energy. This is our "lip sync" stand-in
    // since the static GLB has no morph targets or jaw bone.
    const chestGlow = new THREE.PointLight(0x40b0e0, 0, 3, 1.6)
    chestGlow.position.set(0, 1.25, 0.25)
    scene.add(chestGlow)

    // Soft cyan ground spot
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(2.2, 64),
      new THREE.MeshBasicMaterial({
        color: 0x40b0e0,
        transparent: true,
        opacity: 0.1,
      })
    )
    ground.rotation.x = -Math.PI / 2
    scene.add(ground)

    // ------- Load GLB ----------------------------------------------------
    const modelGroup = new THREE.Group()
    scene.add(modelGroup)

    let mixer: THREE.AnimationMixer | null = null
    const actions: Record<string, THREE.AnimationAction> = {}
    let head: THREE.Object3D | null = null
    let face:
      | (THREE.Mesh & {
          morphTargetInfluences?: number[]
          morphTargetDictionary?: Record<string, number>
        })
      | null = null
    let modelHeight = 1
    let hasAnimations = false

    const loader = new GLTFLoader()
    loader.load(
      ROBOT_URL,
      (gltf) => {
        if (disposed) return
        const root = gltf.scene

        // First measure raw bounding box
        const rawBox = new THREE.Box3().setFromObject(root)
        const rawSize = new THREE.Vector3()
        rawBox.getSize(rawSize)

        // Normalize: scale model so its tallest dimension is exactly TARGET
        const TARGET_HEIGHT = 2.4
        const maxDim = Math.max(rawSize.x, rawSize.y, rawSize.z) || 1
        const scale = TARGET_HEIGHT / maxDim
        root.scale.setScalar(scale)

        // Re-measure after scaling
        const box = new THREE.Box3().setFromObject(root)
        const size = new THREE.Vector3()
        const center = new THREE.Vector3()
        box.getSize(size)
        box.getCenter(center)

        // Re-center horizontally, feet on ground
        root.position.x -= center.x
        root.position.z -= center.z
        root.position.y -= box.min.y

        // Force-disable culling and ensure visibility on every sub-mesh
        let meshCount = 0
        const matSummary: string[] = []
        root.traverse((obj) => {
          obj.frustumCulled = false
          obj.visible = true
          const m = obj as THREE.Mesh
          if (m.isMesh) {
            meshCount++
            const mats = Array.isArray(m.material) ? m.material : [m.material]
            for (const mat of mats) {
              if (!mat) continue
              const std = mat as THREE.MeshStandardMaterial
              std.side = THREE.DoubleSide
              if (std.transparent && std.opacity < 0.05) std.opacity = 1
              std.depthWrite = true
              std.needsUpdate = true
              matSummary.push(
                `${mat.type}:opa=${(mat as THREE.Material & { opacity?: number }).opacity ?? 1}:trans=${(mat as THREE.Material).transparent}`
              )
            }
            m.geometry.computeBoundingSphere()
          }
        })

        modelGroup.add(root)
        modelHeight = size.y

        // eslint-disable-next-line no-console
        console.log('[RobotScene] meshes', meshCount, matSummary.slice(0, 6))

        // Fixed camera — model is normalized so this always works
        camera.position.set(0, modelHeight * 0.55, 4.2)
        camera.lookAt(0, modelHeight * 0.5, 0)
        camera.updateProjectionMatrix()

        // Ground spot
        ground.scale.setScalar(1.2)

        // Find head + face (best-effort by name)
        root.traverse((obj) => {
          const lower = obj.name.toLowerCase()
          if (!head && (lower.includes('head') || lower === 'neck')) head = obj
          const m = obj as THREE.Mesh & {
            morphTargetInfluences?: number[]
            morphTargetDictionary?: Record<string, number>
          }
          if (m.isMesh && m.morphTargetDictionary && !face) face = m
        })

        // Animations (if any)
        if (gltf.animations.length > 0) {
          mixer = new THREE.AnimationMixer(root)
          for (const clip of gltf.animations) {
            actions[clip.name] = mixer.clipAction(clip)
          }
          const idle =
            actions['Idle'] ||
            actions['idle'] ||
            actions['Armature|Idle'] ||
            Object.values(actions)[0]
          if (idle) {
            idle.setLoop(THREE.LoopRepeat, Infinity)
            idle.play()
            hasAnimations = true
          }
        }

        // eslint-disable-next-line no-console
        console.log('[RobotScene] loaded', {
          rawSize: rawSize.toArray().map((n) => n.toFixed(2)),
          scale: scale.toFixed(3),
          finalHeight: modelHeight.toFixed(2),
          animations: Object.keys(actions),
          headName: head?.name,
          hasFace: !!face,
        })
      },
      undefined,
      (err) => {
        // eslint-disable-next-line no-console
        console.error('[RobotScene] failed to load robot.glb', err)
      }
    )

    // ------- Resize ------------------------------------------------------
    const resize = () => {
      const w = Math.max(1, mount.clientWidth)
      const h = Math.max(1, mount.clientHeight)
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    const ro = new ResizeObserver(resize)
    ro.observe(mount)

    // ------- Audio reactivity -------------------------------------------
    let freqData = new Uint8Array(new ArrayBuffer(0))
    function computeIntensity(): number {
      const analyser = analyserGetterRef.current()
      if (!analyser) return 0
      if (freqData.length !== analyser.frequencyBinCount) {
        freqData = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount))
      }
      analyser.getByteFrequencyData(freqData)
      const usable = Math.min(60, freqData.length)
      let sum = 0
      for (let i = 0; i < usable; i++) sum += freqData[i]
      return sum / usable / 255
    }

    // ------- Render loop -------------------------------------------------
    const clock = new THREE.Clock()
    let raf = 0
    let smoothed = 0
    const loop = () => {
      raf = requestAnimationFrame(loop)
      const dt = clock.getDelta()
      mixer?.update(dt)

      const intensity = computeIntensity()
      smoothed += (intensity - smoothed) * (1 - Math.exp(-dt * 8))

      // Drive face morph if available (otherwise no-op)
      if (face && face.morphTargetInfluences && face.morphTargetDictionary) {
        const dict = face.morphTargetDictionary
        const candidates = ['Surprised', 'mouthOpen', 'jawOpen', 'A', 'aa']
        for (const name of candidates) {
          if (dict[name] !== undefined) {
            face.morphTargetInfluences[dict[name]] = Math.min(1, smoothed * 1.6)
            break
          }
        }
      }

      // Subtle head tilt with audio
      if (head) {
        head.rotation.x = -smoothed * 0.18
      }

      // Chest glow pulse — bright cyan when AI is speaking
      const baseGlow = 0.4
      chestGlow.intensity = baseGlow + smoothed * 6.0
      chestGlow.color.setHSL(
        0.55 - smoothed * 0.05, // shift toward cyan
        0.9,
        0.5 + smoothed * 0.15
      )

      // Subtle vertical bob with audio
      modelGroup.position.y = smoothed * 0.04

      // Slow scene rotation: stronger when idle (turntable), gentle sway when active
      const status = useSession.getState().status
      if (status === 'idle') {
        modelGroup.rotation.y = Math.sin(clock.elapsedTime * 0.25) * 0.35
      } else {
        modelGroup.rotation.y = Math.sin(clock.elapsedTime * 0.6) * 0.08
      }

      // Use hasAnimations to satisfy linter / future use
      void hasAnimations

      renderer.render(scene, camera)
    }
    loop()

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      mixer?.stopAllAction()
      scene.traverse((obj) => {
        const m = obj as THREE.Mesh
        if (m.isMesh) {
          m.geometry?.dispose?.()
          const mat = m.material as
            | THREE.Material
            | THREE.Material[]
            | undefined
          if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
          else mat?.dispose?.()
        }
      })
      renderer.dispose()
      renderer.forceContextLoss?.()
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement)
      }
    }
  }, [])

  return <div ref={mountRef} className="relative w-full h-full" />
}
