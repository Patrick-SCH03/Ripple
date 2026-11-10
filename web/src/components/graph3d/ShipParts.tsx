// 3D 배치의 도형: 맥락 선체(반투명 외판 + 구획 경계선, 클릭 대상 아님) · 모델 블록(영향 단계 색) · 이웃 블록 이음면.
import { Edges, Line, QuadraticBezierLine } from '@react-three/drei'
import { type ThreeEvent, useFrame, useThree } from '@react-three/fiber'
import { type RefObject, useEffect, useMemo, useRef } from 'react'
import {
  type BufferGeometry,
  Color,
  DoubleSide,
  type MeshLambertMaterial,
  type MeshStandardMaterial,
  ShaderMaterial,
  Vector3,
} from 'three'
import { SEVERITY_NAMES } from '@/lib/labels'
import type { BlockState } from './blocks'
import { frameLine, hullSkin, jointGeometry, piecesGeometry, propellerGeometry, sheerLine, waterLine } from './geometry'
import { type BlockPlace, FRAME_STATIONS, contextPieces, jointOf, superstructurePieces } from './layout'
import type { TipHandle } from './ShipLabels'
import { type Tokens, severityColor } from './useTokens'
import { type MotionClock, flashGlow, seconds, waveGlow, wavePhase } from './wave'

const NO_RAYCAST = () => null
/** 맥동 주기(초) — 2D 지도의 가장 심각한 카드 맥동과 같다. */
const PULSE_SECONDS = 2.2

let context: {
  skin: { below: BufferGeometry; above: BufferGeometry }
  structure: BufferGeometry
  superstructure: BufferGeometry
  propeller: BufferGeometry
  frames: Vector3[][]
  sheer: Vector3[][]
  water: Vector3[]
} | null = null

/** 맥락 도형(한 번만 만든다). */
function contextShapes() {
  context ??= {
    skin: hullSkin(),
    structure: piecesGeometry(contextPieces(), { step: 2, rows: 16 }),
    superstructure: piecesGeometry(superstructurePieces(), { gap: 0 }),
    propeller: propellerGeometry(),
    frames: FRAME_STATIONS.map((x) => frameLine(x)),
    sheer: [sheerLine(1), sheerLine(-1)],
    water: waterLine(),
  }
  return context
}

/**
 * 반투명 외판 재질: 정면은 거의 비치고 비스듬한 가장자리(윤곽)일수록 짙다 — 안의 블록이 보이면서 선형 윤곽이 또렷하다.
 * 조명 없이 색 + 투명도만(맥락이라 의미색을 쓰지 않는다).
 */
function useShellMaterial(color: string, base: number, rim: number) {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        uniforms: { color: { value: new Color(color) }, base: { value: base }, rim: { value: rim } },
        vertexShader: /* glsl */ `
          varying vec3 vNormal;
          varying vec3 vView;
          void main() {
            vec4 world = modelViewMatrix * vec4(position, 1.0);
            vNormal = normalize(normalMatrix * normal);
            vView = -world.xyz;
            gl_Position = projectionMatrix * world;
          }`,
        fragmentShader: /* glsl */ `
          uniform vec3 color;
          uniform float base;
          uniform float rim;
          varying vec3 vNormal;
          varying vec3 vView;
          void main() {
            float facing = abs(dot(normalize(vNormal), normalize(vView)));
            gl_FragColor = vec4(color, base + rim * pow(1.0 - facing, 2.2));
            #include <colorspace_fragment>
          }`,
        transparent: true,
        depthWrite: false,
        side: DoubleSide,
      }),
    [color, base, rim],
  )
  useEffect(() => () => material.dispose(), [material])
  return material
}

/** 선체 외판 껍질(흘수선 아래는 조금 짙게) + 구획 경계선 + 늑골선 + 현측선 + 흘수선 + 상부 구조 + 프로펠러. */
export function HullContext({ tokens }: { tokens: Tokens }) {
  const shapes = useMemo(() => contextShapes(), [])
  const line = tokens.dark ? tokens.borderStrong : tokens.textMuted
  const above = useShellMaterial(tokens.textMuted, tokens.dark ? 0.05 : 0.04, tokens.dark ? 0.3 : 0.34)
  const below = useShellMaterial(tokens.textSecondary, tokens.dark ? 0.09 : 0.08, tokens.dark ? 0.36 : 0.42)
  return (
    <group>
      <mesh geometry={shapes.skin.above} material={above} raycast={NO_RAYCAST} renderOrder={2} />
      <mesh geometry={shapes.skin.below} material={below} raycast={NO_RAYCAST} renderOrder={2} />
      {/* 다른 화물탱크·기관실 위·코퍼댐 등: 블록 경계선만 은은하게 */}
      <Edges geometry={shapes.structure} threshold={30} color={line} lineWidth={0.7} transparent opacity={tokens.dark ? 0.32 : 0.26} raycast={NO_RAYCAST} />
      <mesh geometry={shapes.superstructure} raycast={NO_RAYCAST} renderOrder={2}>
        <meshStandardMaterial color={tokens.borderStrong} roughness={0.85} transparent opacity={tokens.dark ? 0.16 : 0.22} depthWrite={false} />
        <Edges threshold={30} color={line} lineWidth={0.8} transparent opacity={0.45} raycast={NO_RAYCAST} />
      </mesh>
      <mesh geometry={shapes.propeller} raycast={NO_RAYCAST} renderOrder={2}>
        <meshStandardMaterial color={tokens.textMuted} roughness={0.55} metalness={0.3} transparent opacity={0.55} depthWrite={false} />
      </mesh>
      {shapes.frames.map((points, i) => (
        <Line key={i} points={points} color={line} lineWidth={0.8} transparent opacity={0.4} raycast={NO_RAYCAST} />
      ))}
      {shapes.sheer.map((points, i) => (
        <Line key={`s${i}`} points={points} color={line} lineWidth={1.1} transparent opacity={0.65} raycast={NO_RAYCAST} />
      ))}
      <Line points={shapes.water} color={tokens.textSecondary} lineWidth={1.2} transparent opacity={0.7} raycast={NO_RAYCAST} />
    </group>
  )
}

/** 블록 밝기 움직임에 함께 쓰는 값(움직임 켜짐 · 시계 · 물결 반복 주기). */
export interface BlockMotion {
  live: boolean
  clock: RefObject<MotionClock>
  period: number
}

interface BlockProps {
  place: BlockPlace
  geometry: BufferGeometry
  state: BlockState
  tokens: Tokens
  selected: boolean
  neighbour: boolean
  hovered: boolean
  /** 은은한 맥동(가장 높은 영향 단계 블록, 움직임 켜짐일 때). */
  pulse: boolean
  /** 물결 단계(wave.ts — 영향 블록만, 아니면 null). */
  step: number | null
  /** 목록에서 골라 잠깐 강조(외곽선 + 움직임 켜짐이면 한 번 밝아짐). */
  flash: boolean
  /** 초점 모드에서 경로 밖(영향 블록은 반투명으로 물러남). */
  dim?: boolean
  motion: BlockMotion
  onHover: (code: string | null) => void
  onPick: (id: string) => void
  tip: RefObject<TipHandle | null>
}

/** 물결·강조 맥동이 더하는 밝기(맥동 0.2보다 조금 크게 — 정보보다 눈에 띄지 않게). */
const WAVE_GAIN = 0.28
const FLASH_GAIN = 0.32

function tipDetail(state: BlockState): string {
  const parts = [state.severity ? `영향 ${SEVERITY_NAMES[state.severity]} · ${state.impacts}건` : '영향 없음']
  if (state.target) parts.push('바꾸는 부재')
  if (state.pick) parts.push('누르면 근거')
  return parts.join(' · ')
}

/** 모델 블록 하나: 영향 블록은 불투명 단계 색(무광 강재), 영향 없는 블록은 반투명(뒤의 영향 블록이 비쳐 보이게). */
export function BlockMesh(props: BlockProps) {
  const { place, geometry, state, tokens, selected, neighbour, hovered, pulse, step, flash, dim = false, motion, onHover, onPick, tip } = props
  const affected = state.severity !== null
  const color = severityColor(state.severity, tokens)
  const pickable = state.pick !== null
  const edge = selected ? tokens.focus : state.target || neighbour ? tokens.text : tokens.textSecondary
  const width = selected ? 3 : state.target ? 2.2 : neighbour || hovered ? 1.6 : 1
  const glow = selected ? 0.16 : hovered ? 0.2 : 0.05
  const material = useRef<MeshStandardMaterial | MeshLambertMaterial | null>(null)
  const size = useThree((s) => s.size)
  const invalidate = useThree((s) => s.invalidate)
  const animating = pulse || (motion.live && (step !== null || flash))

  useFrame(() => {
    if (!animating || !material.current) return
    const clock = motion.clock.current
    const { period } = motion
    const now = seconds()
    let value = glow
    if (pulse) value += 0.2 * ((1 - Math.cos((now * 2 * Math.PI) / PULSE_SECONDS)) / 2)
    if (motion.live && step !== null) value += WAVE_GAIN * waveGlow(step, wavePhase(now - clock.waveStart, period))
    if (motion.live && flash) value += FLASH_GAIN * flashGlow(now - clock.flashStart)
    material.current.emissiveIntensity = value
  })
  // 움직임을 멈추면 밝기를 제자리로(prop이 같아도 다시 쓴다)
  useEffect(() => {
    if (animating || !material.current) return
    material.current.emissiveIntensity = glow
    invalidate()
  }, [animating, glow, invalidate])
  const bind = (value: MeshStandardMaterial | MeshLambertMaterial | null) => {
    material.current = value
  }

  const moveTip = (event: ThreeEvent<PointerEvent>) => {
    const x = ((event.pointer.x + 1) / 2) * size.width
    const y = ((1 - event.pointer.y) / 2) * size.height
    tip.current?.show(`${place.code} ${place.name}`, tipDetail(state), x, y)
  }
  const events = pickable
    ? {
        onClick: (event: ThreeEvent<MouseEvent>) => {
          event.stopPropagation()
          if (state.pick) onPick(state.pick)
        },
        onPointerOver: (event: ThreeEvent<PointerEvent>) => {
          event.stopPropagation()
          onHover(place.code)
          moveTip(event)
        },
        onPointerMove: (event: ThreeEvent<PointerEvent>) => {
          event.stopPropagation()
          moveTip(event)
        },
        onPointerOut: () => {
          onHover(null)
          tip.current?.hide()
        },
      }
    : { raycast: NO_RAYCAST }
  return (
    <mesh geometry={geometry} renderOrder={affected ? 0 : 3} castShadow={affected} receiveShadow={affected} {...events}>
      {affected ? (
        // 초점 모드 경로 밖이면 반투명으로(재질을 바꿔 끼워 투명 정렬을 다시 잡는다)
        <meshStandardMaterial key={dim ? 'dim' : 'solid'} ref={bind} color={color} roughness={0.8} metalness={0.12} emissive={color}
          emissiveIntensity={glow} transparent={dim} opacity={dim ? 0.22 : 1} depthWrite={!dim} />
      ) : (
        // 영향 없는 블록은 반투명이라 화면을 넓게 덮는다 — 가벼운 램버트 재질(내장 그래픽의 채우기 부담을 줄임)
        <meshLambertMaterial
          ref={bind}
          color={color}
          transparent
          opacity={tokens.dark ? 0.42 : 0.5}
          depthWrite={false}
          emissive={color}
          emissiveIntensity={glow}
        />
      )}
      <Edges threshold={35} color={edge} lineWidth={width} transparent={dim} opacity={dim ? 0.35 : 1} raycast={NO_RAYCAST} renderOrder={4} />
      {/* 고른 블록(목록에서 잠깐 강조한 블록도)은 다른 블록·외판에 가려도 외곽선이 비쳐 보이게 */}
      {(selected || flash) && (
        <Edges
          threshold={35}
          color={tokens.focus}
          lineWidth={flash && !selected ? 2.2 : 1.4}
          depthTest={false}
          transparent
          opacity={flash && !selected ? 0.9 : 0.5}
          raycast={NO_RAYCAST}
          renderOrder={11}
        />
      )}
    </mesh>
  )
}

/**
 * 고른 블록과 이웃 블록의 이음면(맞대기 용접 자리)을 얇은 판으로 강조한다(가려도 비쳐 보이게). 떨어져 있는 이웃(펌프룸 ↔ No.3
 * 횡격벽처럼 배치 표에서 맞닿지 않는 쌍)은 블록 위로 낮게 휜 점선으로 잇는다.
 */
export function AdjacencyJoints({
  code,
  neighbours,
  centers,
  color,
}: {
  code: string
  neighbours: readonly string[]
  centers: ReadonlyMap<string, Vector3>
  color: string
}) {
  const joints = useMemo(
    () =>
      neighbours.map((other) => {
        const joint = jointOf(code, other)
        return { other, geometry: joint ? jointGeometry(joint) : null }
      }),
    [code, neighbours],
  )
  useEffect(() => () => joints.forEach(({ geometry }) => geometry?.dispose()), [joints])
  const from = centers.get(code)
  return (
    <>
      {joints.map(({ other, geometry }) =>
        geometry ? (
          <mesh key={other} geometry={geometry} raycast={NO_RAYCAST} renderOrder={9}>
            <meshBasicMaterial
              color={color}
              transparent
              opacity={0.16}
              depthWrite={false}
              side={DoubleSide}
              polygonOffset
              polygonOffsetFactor={-2}
              polygonOffsetUnits={-2}
            />
            <Edges threshold={30} color={color} lineWidth={1.6} depthTest={false} transparent opacity={0.9} raycast={NO_RAYCAST} renderOrder={10} />
          </mesh>
        ) : (
          from && centers.get(other) && <LowArc key={other} from={from} to={centers.get(other) as Vector3} color={color} />
        ),
      )}
    </>
  )
}

/** 떨어진 이웃 블록 잇기: 두 블록 중 높은 쪽보다 조금만 위로 휜 점선(블록 위로 크게 솟지 않게). */
function LowArc({ from, to, color }: { from: Vector3; to: Vector3; color: string }) {
  const mid = useMemo(() => {
    const point = from.clone().add(to).multiplyScalar(0.5)
    point.y = Math.max(from.y, to.y) + 2 + from.distanceTo(to) * 0.04
    return point
  }, [from, to])
  return (
    <QuadraticBezierLine
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
      raycast={NO_RAYCAST}
      renderOrder={10}
    />
  )
}
