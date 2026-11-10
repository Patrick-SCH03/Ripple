// 3D 배치의 움직임(2D 영향 지도의 단계별 나타나기·흐르는 점선·맥동과 같은 뜻, 순서·밝기 계산은 wave.ts):
// - 물결: 시작 블록(바꾸는 부재)에서 고리가 한 번 퍼지고, 블록이 단계 순으로 밝아진다(BlockMesh가 clock으로 밝기를 정함).
// - 이음면 흐름: 단계가 다른 이웃 블록의 이음면은 굵게 맥동(ShipRelations WeldSeams), 떨어진 이웃은 낮은 호 점선이 앞 → 뒤
//   단계로 흐름(관계 화살표가 있는 쌍은 화살표만).
// - 움직임을 멈추면(위 막대 '움직임 멈춤', 움직임 줄이기면 처음부터 멈춤) 고리·밝기 변화는 지우고 점선은 멈춘 채 둔다.
// 그리기: frameloop demand 그대로 — 물결·강조 중에는 초당 30장, 쉬는 동안은 맥동이 있을 때만 초당 20장, 탭이 숨었거나 칸이
// 화면 밖이면 멈춘다.
import { QuadraticBezierLine, type QuadraticBezierLineRef } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { type RefObject, useEffect, useMemo, useRef } from 'react'
import { DoubleSide, type Mesh, type MeshBasicMaterial, type Vector3 } from 'three'
import { jointOf } from './layout'
import { type MotionClock, type WaveFlow, type WavePlan, busy, ringAt, seconds, wavePhase } from './wave'

const NO_RAYCAST = () => null

interface DriverProps {
  /** 움직임 켜짐. */
  live: boolean
  /** 쉬는 동안에도 움직이는 것(맥동·흐르는 점선)이 있나. */
  steady: boolean
  plan: WavePlan
  clock: RefObject<MotionClock>
  /** 바뀌면 다시 깨운다(목록에서 골라 강조 맥동을 시작할 때). */
  wake: number
}

/** 움직이는 동안만 다시 그리기를 요청한다. 물결이 끝나 쉬는 동안 steady가 없으면 다음 물결 차례까지 잔다. */
export function MotionDriver({ live, steady, plan, clock, wake }: DriverProps) {
  const invalidate = useThree((state) => state.invalidate)
  const canvas = useThree((state) => state.gl.domElement)
  useEffect(() => {
    if (!live) return
    let visible = true
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(([entry]) => (visible = entry.isIntersecting))
    observer?.observe(canvas)
    let timer = 0
    const tick = () => {
      const now = seconds()
      const active = busy(clock.current, plan, now)
      if (visible && !document.hidden && (active || steady)) invalidate()
      let wait = active ? 1000 / 30 : 1000 / 20
      if (!active && !steady) {
        // 다음 물결까지 잔다(강조 맥동은 wake가 바뀌어 다시 깨운다)
        const phase = wavePhase(now - clock.current.waveStart, plan.period)
        const next = phase < 0 ? -phase : plan.period - phase
        wait = Math.min(1000, Math.max(1000 / 20, next * 1000))
      }
      timer = window.setTimeout(tick, wait)
    }
    tick()
    return () => {
      window.clearTimeout(timer)
      observer?.disconnect()
    }
  }, [live, steady, plan, clock, wake, invalidate, canvas])
  return null
}

/** 시작 블록에서 수평으로 퍼지는 고리 하나(물결 한 바퀴마다 한 번, 가려도 보이게 은은하게). */
export function WaveRing({ at, clock, period, color }: { at: Vector3; clock: RefObject<MotionClock>; period: number; color: string }) {
  const mesh = useRef<Mesh>(null)
  const material = useRef<MeshBasicMaterial>(null)
  useFrame(() => {
    const ring = ringAt(wavePhase(seconds() - clock.current.waveStart, period))
    if (!mesh.current || !material.current) return
    mesh.current.visible = ring !== null
    if (!ring) return
    const radius = 3 + 31 * ring.scale
    mesh.current.scale.set(radius, radius, 1)
    material.current.opacity = 0.32 * ring.opacity
  })
  return (
    <mesh ref={mesh} position={at} rotation={[-Math.PI / 2, 0, 0]} raycast={NO_RAYCAST} renderOrder={12} visible={false}>
      <ringGeometry args={[0.93, 1, 64]} />
      <meshBasicMaterial ref={material} color={color} transparent opacity={0} depthTest={false} depthWrite={false} side={DoubleSide} />
    </mesh>
  )
}

/**
 * 영향이 건너간 이음 중 맞닿지 않은 쌍(배치 표에서 떨어진 이웃)의 낮은 호 점선(앞 단계 → 뒤 단계). 맞닿은 쌍은 용접 이음면
 * 강조(ShipRelations WeldSeams), 같은 쌍에 관계 화살표가 있으면(skip — `${from}>${to}`) 화살표만.
 */
export function JointFlows({
  flows,
  centers,
  color,
  live,
  skip,
}: {
  flows: readonly WaveFlow[]
  centers: ReadonlyMap<string, Vector3>
  color: string
  live: boolean
  skip: ReadonlySet<string>
}) {
  return (
    <>
      {flows.map((flow) => {
        const key = `${flow.from}>${flow.to}`
        if (jointOf(flow.from, flow.to) || skip.has(key) || skip.has(`${flow.to}>${flow.from}`)) return null
        const from = centers.get(flow.from)
        const to = centers.get(flow.to)
        return from && to ? <FlowArc key={key} from={from} to={to} color={color} live={live} /> : null
      })}
    </>
  )
}

/** 점선이 흐르는 속도(m/초 — 2D 주요 경로 점선이 1초에 한 마디 흐르는 것과 비슷하게). */
const FLOW_SPEED = 2.4

function FlowArc({ from, to, color, live }: { from: Vector3; to: Vector3; color: string; live: boolean }) {
  const line = useRef<QuadraticBezierLineRef>(null)
  const mid = useMemo(() => {
    const point = from.clone().add(to).multiplyScalar(0.5)
    point.y = Math.max(from.y, to.y) + 2 + from.distanceTo(to) * 0.04
    return point
  }, [from, to])
  useFrame(() => {
    if (live && line.current) line.current.material.dashOffset = -seconds() * FLOW_SPEED
  })
  return (
    <QuadraticBezierLine
      ref={line}
      start={from}
      end={to}
      mid={mid}
      color={color}
      lineWidth={2}
      dashed
      dashSize={1.6}
      gapSize={1}
      depthTest={false}
      transparent
      opacity={0.85}
      raycast={NO_RAYCAST}
      renderOrder={10}
    />
  )
}
