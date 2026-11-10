// 3D 블록 사이 관계 그리기(계산은 relations.ts, 도형은 relationShapes.ts):
// - 관계 화살표: 출발 블록 위 → 선체 위로 휘어 → 도착 블록 위, 끝에 화살촉. 점선이 화살 방향으로 흐른다(움직임 멈춤이면 정지).
//   색 = 도착 블록 영향 단계. 초점 모드(블록을 고름)면 그 블록까지 오는 화살표만 남기고 나머지는 옅게.
// - 용접 이음면: 영향이 건너간 이음은 도착 블록 단계 색 굵은 테두리 + 옅은 면 맥동, 바꾸는 블록의 나머지 이음면은 옅은 테두리.
// 화살표·이음면 수가 적어(화살표 최대 8) 도형은 처음 한 번 만들고(이음면은 모듈 캐시) 재질 값만 프레임마다 바꾼다.
import { Edges, type EdgesRef, QuadraticBezierLine, type QuadraticBezierLineRef } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import { type BufferGeometry, ConeGeometry, DoubleSide, type MeshBasicMaterial } from 'three'
import { type ArrowShape, seamShape } from './relationShapes'
import type { FocusPath, SeamPlan } from './relations'
import { type Tokens, severityColor } from './useTokens'
import { seconds } from './wave'

const NO_RAYCAST = () => null
/** 점선 흐름 속도(m/초 — 이음면 흐름과 같게). */
const FLOW_SPEED = 2.4
/** 이음면 맥동 주기(초 — 블록 맥동과 같다). */
const PULSE_SECONDS = 2.2
const HEAD = { radius: 1.7, height: 4.6 } as const
const head = new ConeGeometry(HEAD.radius, HEAD.height, 16)
head.translate(0, -HEAD.height / 2, 0) // 꼭짓점이 원점(곡선 끝)에 오게
/** 움직임을 멈췄을 때 굵은 이음면의 면·테두리 불투명도. */
const STILL = { face: 0.22, edge: 1 } as const

export function RelationArrows({ arrows, focus, tokens, live }: { arrows: readonly ArrowShape[]; focus: FocusPath | null; tokens: Tokens; live: boolean }) {
  return (
    <>
      {arrows.map((arrow) => (
        <Arrow
          key={arrow.link.key}
          arrow={arrow}
          color={severityColor(arrow.link.severity, tokens)}
          halo={tokens.surface}
          dim={focus !== null && !focus.links.has(arrow.link.key)}
          live={live}
        />
      ))}
    </>
  )
}

/** 화살표 하나: 바탕색 테두리(같은 색 블록 위에서도 보이게) + 단계 색 흐르는 점선 + 화살촉. */
function Arrow({ arrow, color, halo, dim, live }: { arrow: ArrowShape; color: string; halo: string; dim: boolean; live: boolean }) {
  const line = useRef<QuadraticBezierLineRef>(null)
  useFrame(() => {
    if (live && !dim && line.current) line.current.material.dashOffset = -seconds() * FLOW_SPEED
  })
  const opacity = dim ? 0.14 : 1
  const curve = { start: arrow.from, end: arrow.to, mid: arrow.control, depthTest: false, transparent: true, raycast: NO_RAYCAST }
  return (
    <group>
      {!dim && <QuadraticBezierLine {...curve} color={halo} lineWidth={8} opacity={0.9} renderOrder={12} />}
      <QuadraticBezierLine ref={line} {...curve} color={color} lineWidth={dim ? 2 : 4.5} dashed dashSize={2.4} gapSize={1.2} opacity={opacity} renderOrder={13} />
      <mesh geometry={head} position={arrow.to} quaternion={arrow.turn} raycast={NO_RAYCAST} renderOrder={14}>
        <meshBasicMaterial color={color} transparent opacity={opacity} depthTest={false} depthWrite={false} />
      </mesh>
    </group>
  )
}

export function WeldSeams({ seams, tokens, live }: { seams: readonly SeamPlan[]; tokens: Tokens; live: boolean }) {
  return (
    <>
      {seams.map((seam) => {
        const shape = seamShape(seam.a, seam.b)
        if (!shape) return null
        return seam.strong ? (
          <StrongSeam key={seam.key} geometry={shape.geometry} color={severityColor(seam.severity, tokens)} halo={tokens.surface} live={live} />
        ) : (
          // 바꾸는 블록의 나머지 이음면: 맥동 없이 바탕색 테두리 위 바꾸는 블록 단계 색
          <group key={seam.key}>
            <Edges geometry={shape.geometry} threshold={30} color={tokens.surface} lineWidth={5} depthTest={false} transparent opacity={0.8} raycast={NO_RAYCAST} renderOrder={10} />
            <Edges geometry={shape.geometry} threshold={30} color={severityColor(seam.severity, tokens)} lineWidth={2.4} depthTest={false} transparent opacity={0.9} raycast={NO_RAYCAST} renderOrder={11} />
          </group>
        )
      })}
    </>
  )
}

/** 영향이 건너간 이음면: 바탕색 테두리 위 단계 색 굵은 테두리 + 옅은 면, 움직임 켜짐이면 은은하게 맥동(깜빡임 없음). */
function StrongSeam({ geometry, color, halo, live }: { geometry: BufferGeometry; color: string; halo: string; live: boolean }) {
  const face = useRef<MeshBasicMaterial>(null)
  const edges = useRef<EdgesRef>(null)
  useFrame(() => {
    if (!face.current || !edges.current) return
    const wave = live ? (1 - Math.cos((seconds() * 2 * Math.PI) / PULSE_SECONDS)) / 2 : 1
    face.current.opacity = live ? 0.12 + 0.24 * wave : STILL.face
    edges.current.material.opacity = live ? 0.6 + 0.4 * wave : STILL.edge
  })
  return (
    <mesh geometry={geometry} raycast={NO_RAYCAST} renderOrder={9}>
      <meshBasicMaterial ref={face} color={color} transparent opacity={STILL.face} depthTest={false} depthWrite={false} side={DoubleSide} />
      <Edges threshold={30} color={halo} lineWidth={8} depthTest={false} transparent opacity={0.85} raycast={NO_RAYCAST} renderOrder={10} />
      <Edges ref={edges} threshold={30} color={color} lineWidth={4} depthTest={false} transparent opacity={STILL.edge} raycast={NO_RAYCAST} renderOrder={11} />
    </mesh>
  )
}