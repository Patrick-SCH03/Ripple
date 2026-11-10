// 3D 배치 장면(three · react-three-fiber): 맥락 선체 + 모델 블록 + 라벨 + 이웃 이음면 + 물결·이음면 흐름 + 카메라 조작.
// 마우스: 왼쪽 끌기 회전 · 오른쪽 끌기 이동 · 휠 확대(커서 쪽으로, 캔버스 위에서만 — 밖은 페이지 스크롤).
// 터치: 한 손가락 회전 · 두 손가락 확대·이동. 시점 단추는 정한 방향에서 상자를 맞추고, 움직임 줄이기면 바로 옮긴다(ShipControls).
// 성능: 필요할 때만 그린다(frameloop demand — 카메라·선택·움직임 때만, ShipMotion MotionDriver). 그림자는 주광 하나의 1024
// 지도(영향 블록끼리만), 은은한 음영은 방 환경광(RoomEnvironment, 처음 한 번 만듦)과 외판 윤곽 재질로.
import { Canvas, useThree } from '@react-three/fiber'
import { type RefObject, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { type DirectionalLight, Object3D, PMREMGenerator } from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { SEVERITY_RANK } from '@/lib/labels'
import { type BlockState, neighboursOf } from './blocks'
import { blockShapes } from './geometry'
import { SHIP } from './hull'
import { ADJACENCY, BLOCK_LAYOUT } from './layout'
import type { LabelElements } from './labelPlace'
import { type FlyRequest, ShipControls, type ViewRequest } from './ShipControls'
import { type ExtraAnchor, LabelProjector, type OverlayLabel, type TipHandle } from './ShipLabels'
import { JointFlows, MotionDriver, WaveRing } from './ShipMotion'
import type { ArrowShape } from './relationShapes'
import { RelationArrows, WeldSeams } from './ShipRelations'
import { AdjacencyJoints, type BlockMotion, BlockMesh, HullContext } from './ShipParts'
import { type Tokens, useTokens } from './useTokens'
import type { FocusPath, SeamPlan } from './relations'
import { type MotionClock, WAVE, type WavePlan, seconds } from './wave'

export type { FlyRequest, ViewRequest } from './ShipControls'

/** 목록·근거에서 골라 잠깐 강조할 블록(고를 때마다 seq가 늘어남, 끝나면 Ship3DView가 지운다). */
export interface FlashRequest {
  codes: readonly string[]
  seq: number
}

interface Props {
  states: ReadonlyMap<string, BlockState>
  selectedCode: string | null
  onPick: (id: string) => void
  onClear: () => void
  view: ViewRequest
  /** 전체 화면 중(들어가고 나올 때 다시 맞춘다). */
  full: boolean
  /** 라벨 DOM(캔버스 위 겹 — ShipLabels LabelLayer). */
  labels: LabelElements
  /** 블록 이름 툴팁(캔버스 위 겹 — ShipLabels HoverTip). */
  tip: RefObject<TipHandle | null>
  /** 움직임 켜짐(맥동·물결·이음면 흐름 — 2D 지도 '움직임 멈춤/켜기'와 같은 설정). */
  motion: boolean
  /** 물결 순서·이음면 흐름(wave.ts). */
  plan: WavePlan
  /** 목록·근거에서 고른 블록으로 날아가기. */
  fly: FlyRequest | null
  flash: FlashRequest | null
  /** 블록 사이 관계 화살표 · 용접 이음면 · 초점 모드(relations.ts, 고른 블록이 있을 때만 focus). */
  relations: SceneRelations
}

export interface SceneRelations {
  arrows: readonly ArrowShape[]
  seams: readonly SeamPlan[]
  focus: FocusPath | null
  /** 관계·이음면 이름표 자리(라벨 겹이 함께 비켜 놓는다)와 글(라벨 겹 LabelLayer). */
  anchors: readonly ExtraAnchor[]
  labels: readonly OverlayLabel[]
}

const FOV = 30
const MID_X = (SHIP.aftEnd + SHIP.fwdEnd) / 2

export function ShipCanvas({ states, selectedCode, onPick, onClear, view, full, labels, tip, motion, plan, fly, flash, relations }: Props) {
  const tokens = useTokens()
  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 1.5]}
      shadows="percentage"
      flat
      camera={{ fov: FOV, near: 1, far: 5000, position: [140, 160, 520] }}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      onPointerMissed={(event) => {
        if (event.button === 0) onClear()
      }}
      aria-label="3D 배치 보기"
    >
      <color attach="background" args={[tokens.surface]} />
      <Lights tokens={tokens} />
      <HullContext tokens={tokens} />
      <Blocks
        states={states}
        selectedCode={selectedCode}
        onPick={onPick}
        tokens={tokens}
        tip={tip}
        motion={motion}
        plan={plan}
        flash={flash}
        relations={relations}
      />
      <LabelProjector elements={labels} extra={relations.anchors} />
      <ShipControls view={view} full={full} fly={fly} />
    </Canvas>
  )
}

/** 하늘·바닥 반구광 + 그림자를 드리우는 주광(왼쪽 위 앞) + 보조광 + 방 환경광(무광 강재가 평평해 보이지 않게). */
function Lights({ tokens }: { tokens: Tokens }) {
  const get = useThree((state) => state.get)
  const invalidate = useThree((state) => state.invalidate)
  const target = useMemo(() => {
    const object = new Object3D()
    object.position.set(MID_X, 0, 0)
    return object
  }, [])
  // 그림자 카메라 범위를 배 전체에(속성으로 바꾸면 투영 행렬이 다시 계산되지 않아 직접 맞춘다)
  const key = useRef<DirectionalLight>(null)
  useLayoutEffect(() => {
    const light = key.current
    if (!light) return
    const camera = light.shadow.camera
    Object.assign(camera, { left: -170, right: 170, top: 90, bottom: -90, near: 10, far: 700 })
    camera.updateProjectionMatrix()
    light.shadow.mapSize.set(1024, 1024)
    light.shadow.bias = -0.0004
    light.shadow.normalBias = 0.4
    light.shadow.radius = 4
    // 빛과 블록은 움직이지 않으니 그림자 지도는 블록 상태가 바뀔 때만 다시 그린다(카메라를 돌려도 그대로) — Blocks가 켠다
    const { gl } = get()
    gl.shadowMap.autoUpdate = false
    gl.shadowMap.needsUpdate = true
    invalidate()
  }, [get, invalidate])
  // 장면·렌더러는 three 객체라 효과 안에서 꺼내 설정한다
  useEffect(() => {
    const { gl, scene } = get()
    const pmrem = new PMREMGenerator(gl)
    const room = new RoomEnvironment()
    const texture = pmrem.fromScene(room, 0.04).texture
    scene.environment = texture
    room.dispose()
    pmrem.dispose()
    invalidate()
    return () => {
      scene.environment = null
      texture.dispose()
    }
  }, [get, invalidate])
  useEffect(() => {
    get().scene.environmentIntensity = tokens.dark ? 0.35 : 0.45
    invalidate()
  }, [get, tokens.dark, invalidate])
  return (
    <>
      <primitive object={target} />
      <hemisphereLight args={['#ffffff', tokens.dark ? '#2a2e35' : '#b9c0ca', tokens.dark ? 1.1 : 1.15]} />
      <directionalLight ref={key} position={[MID_X - 150, 260, 200]} target={target} intensity={tokens.dark ? 1.3 : 1.6} castShadow />
      <directionalLight position={[MID_X + 180, 140, -200]} intensity={tokens.dark ? 0.45 : 0.55} />
    </>
  )
}

type BlocksProps = Pick<Props, 'states' | 'selectedCode' | 'onPick' | 'tip' | 'motion' | 'plan' | 'flash' | 'relations'> & { tokens: Tokens }

function Blocks({ states, selectedCode, onPick, tokens, tip, motion, plan, flash, relations }: BlocksProps) {
  const shapes = useMemo(() => blockShapes(), [])
  const centers = useMemo(() => new Map([...shapes].map(([code, shape]) => [code, shape.center])), [shapes])
  const [hovered, setHovered] = useState<string | null>(null)
  const neighbours = useMemo(() => (selectedCode ? neighboursOf(selectedCode, ADJACENCY) : []), [selectedCode])
  // 용접 이음면으로 이미 그린 쌍은 고른 블록 이음면에서 빼고, 화살표가 있는 쌍은 낮은 호를 그리지 않는다
  const seamKeys = useMemo(() => new Set(relations.seams.map((seam) => seam.key)), [relations.seams])
  const arrowKeys = useMemo(() => new Set(relations.arrows.map((arrow) => arrow.link.key)), [relations.arrows])
  // 맥동: 가장 높은 영향 단계의 블록(2D 지도에서 맥동하는 가장 심각한 카드와 같은 뜻)
  const top = useMemo(() => {
    const ranks = [...states.values()].flatMap((state) => (state.severity ? [SEVERITY_RANK[state.severity]] : []))
    return ranks.length ? Math.max(...ranks) : null
  }, [states])
  const pulsing = (state: BlockState) => motion && top !== null && state.severity !== null && SEVERITY_RANK[state.severity] === top
  // 물결 시계: 결과가 바뀌거나 움직임을 다시 켜면 잠깐 뒤 첫 물결부터(프레임마다 읽는 값이라 그리기 상태로 두지 않는다)
  const clock = useRef<MotionClock>({ waveStart: Infinity, flashStart: -Infinity })
  const blockMotion = useMemo<BlockMotion>(() => ({ live: motion, clock, period: plan.period }), [motion, plan.period])
  useEffect(() => {
    if (motion) clock.current.waveStart = seconds() + WAVE.delay
  }, [motion, plan])
  useEffect(() => {
    if (flash) clock.current.flashStart = seconds()
  }, [flash])
  // 라벨(캔버스 밖 DOM)이 바뀐 뒤에도 자리를 다시 잡도록 한 장 더 그린다(frameloop demand)
  const invalidate = useThree((state) => state.invalidate)
  const get = useThree((state) => state.get)
  useEffect(() => invalidate(), [states, selectedCode, hovered, flash, motion, relations, invalidate])
  // 영향 블록(그림자를 드리우는 블록)이 바뀌면 그림자 지도를 한 번 다시 그린다
  useEffect(() => {
    get().gl.shadowMap.needsUpdate = true
    invalidate()
  }, [states, get, invalidate])
  useEffect(() => {
    document.body.style.cursor = hovered ? 'pointer' : ''
    return () => {
      document.body.style.cursor = ''
    }
  }, [hovered])
  return (
    <>
      <MotionDriver
        live={motion}
        steady={top !== null || plan.flows.length > 0 || relations.arrows.length > 0 || relations.seams.some((seam) => seam.strong)}
        plan={plan}
        clock={clock}
        wake={flash?.seq ?? 0}
      />
      {BLOCK_LAYOUT.map((place) => {
        const state = states.get(place.code)
        const shape = shapes.get(place.code)
        if (!state || !shape) return null
        return (
          <BlockMesh
            key={place.code}
            place={place}
            geometry={shape.geometry}
            state={state}
            tokens={tokens}
            selected={selectedCode === place.code}
            neighbour={neighbours.includes(place.code)}
            hovered={hovered === place.code}
            pulse={pulsing(state)}
            step={plan.steps.get(place.code) ?? null}
            flash={flash?.codes.includes(place.code) ?? false}
            dim={relations.focus !== null && !relations.focus.blocks.has(place.code)}
            motion={blockMotion}
            onHover={setHovered}
            onPick={onPick}
            tip={tip}
          />
        )
      })}
      {selectedCode && (
        <AdjacencyJoints
          code={selectedCode}
          neighbours={neighbours.filter((other) => !seamKeys.has(selectedCode < other ? `${selectedCode}|${other}` : `${other}|${selectedCode}`))}
          centers={centers}
          color={tokens.primary}
        />
      )}
      <WeldSeams seams={relations.seams} tokens={tokens} live={motion} />
      <JointFlows flows={plan.flows} centers={centers} color={tokens.primary} live={motion} skip={arrowKeys} />
      <RelationArrows arrows={relations.arrows} focus={relations.focus} tokens={tokens} live={motion} />
      {motion &&
        plan.origins.map((code) => {
          const at = centers.get(code)
          return at ? <WaveRing key={code} at={at} clock={clock} period={plan.period} color={tokens.primary} /> : null
        })}
    </>
  )
}
