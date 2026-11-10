// 3D 배치 라벨(캔버스 위 DOM 한 겹): 블록 코드 + 영향 블록이면 단계, 맥락 이름표(화물탱크 번호·선수·선미), 라벨 끈(SVG),
// 마우스를 올린 블록의 이름 툴팁. 자리는 장면 안의 LabelProjector가 그릴 때마다 3D 좌표를 화면 좌표로 옮기고, 겹치면
// labelPlace가 비켜 놓거나 숨긴다(React 다시 그리기 없이 transform·속성을 바로 쓴다).
// 누를 수 있는 블록 라벨은 단추라 키보드(Tab · Enter)로도 블록을 고른다.
import { useFrame, useThree } from '@react-three/fiber'
import { type RefObject, useImperativeHandle, useRef } from 'react'
import { Vector3 } from 'three'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import { SEVERITY_NAMES, SEVERITY_RANK } from '@/lib/labels'
import { cn } from '@/lib/utils'
import type { BlockState } from './blocks'
import { blockShapes } from './geometry'
import { type LabelElements, type LabelInput, placeLabels } from './labelPlace'
import { BLOCK_LAYOUT, CONTEXT_LABELS, LABEL_ANCHORS } from './layout'
import { hopName } from './relations'

const point = new Vector3()

/** 라벨 우선순위(겹칠 때 높은 쪽이 제자리를 갖는다). */
function priorityOf(state: BlockState, selected: boolean): number {
  return (selected ? 1000 : 0) + (state.target ? 100 : 0) + (state.severity ? (SEVERITY_RANK[state.severity] + 1) * 10 : 0) + (state.pick ? 5 : 1)
}

/** 3D 점 → 캔버스 px(카메라 뒤면 null). */
function toScreen(at: Vector3, camera: Parameters<Vector3['project']>[0], width: number, height: number): [number, number] | null {
  point.copy(at).project(camera)
  if (point.z > 1 || point.z < -1) return null
  return [((point.x + 1) / 2) * width, ((1 - point.y) / 2) * height]
}

/**
 * 장면 안: 그릴 때마다 라벨 자리를 화면 좌표로. 카메라 뒤면 숨기고, 겹치면 우선순위(고른 블록 > 바꾸는 부재 > 높은 영향 단계 >
 * 맥락 이름표) 낮은 쪽을 비켜 놓거나 숨긴다. 고른 블록·초점이 있는 라벨은 숨기지 않는다. 라벨 끈은 블록 가운데 → 라벨.
 */
/** 블록 밖 이름표(관계 화살표 가운데 · 용접 이음면) 자리 — 블록 라벨과 함께 비켜 놓는다(라벨 끈 없음). */
export interface ExtraAnchor {
  key: string
  at: Vector3
}

export function LabelProjector({ elements, extra = [] }: { elements: LabelElements; extra?: readonly ExtraAnchor[] }) {
  const size = useThree((state) => state.size)
  const centers = useRef(new Map([...blockShapes()].map(([code, shape]) => [code, shape.center])))
  const anchors = useRef(LABEL_ANCHORS.map((anchor) => ({ key: anchor.key, at: new Vector3(...anchor.at) })))
  useFrame(({ camera }) => {
    const inputs: LabelInput[] = []
    const ends = new Map<string, [number, number] | null>()
    for (const anchor of [...anchors.current, ...extra]) {
      const element = elements.labels.get(anchor.key)
      if (!element) continue
      const screen = toScreen(anchor.at, camera, size.width, size.height)
      if (!screen) {
        element.style.visibility = 'hidden'
        continue
      }
      const priority = Number(element.dataset.priority ?? 0)
      point.copy(anchor.at).project(camera)
      inputs.push({
        key: anchor.key,
        x: screen[0],
        y: screen[1],
        w: element.offsetWidth,
        h: element.offsetHeight,
        priority,
        depth: point.z,
        movable: !anchor.key.startsWith('ctx:'),
        pinned: priority >= 1000 || element === document.activeElement,
      })
      const center = centers.current.get(anchor.key)
      if (center) ends.set(anchor.key, toScreen(center, camera, size.width, size.height))
    }
    const spots = placeLabels(inputs, size.width, size.height)
    for (const [key, spot] of spots) {
      const element = elements.labels.get(key)
      if (!element) continue
      element.style.visibility = spot.visible ? 'visible' : 'hidden'
      element.style.transform = `translate(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px) translate(-50%, -50%)`
      element.style.zIndex = String(Math.min(999, Number(element.dataset.priority ?? 0)))
      const leader = elements.leaders.get(key)
      if (!leader) continue
      const end = ends.get(key)
      const long = end && Math.hypot(end[0] - spot.x, end[1] - spot.y) > 16
      leader.style.visibility = spot.visible && long ? 'visible' : 'hidden'
      if (end && long) {
        leader.setAttribute('x1', end[0].toFixed(1))
        leader.setAttribute('y1', end[1].toFixed(1))
        leader.setAttribute('x2', spot.x.toFixed(1))
        leader.setAttribute('y2', spot.y.toFixed(1))
      }
    }
  })
  return null
}

/** 블록 밖 이름표 한 개(관계 화살표 '맞대기 용접 2곳' · 고른 블록의 '용접 이음면'). */
export interface OverlayLabel {
  key: string
  text: string
  /** 초점 경로에 남은 관계(굵게 · 앞자리). */
  strong: boolean
}

/** 관계 이름표 우선순위: 영향 없는 블록 라벨보다 앞, 영향 블록 라벨보다 뒤(초점 경로면 고른 블록 다음). */
const OVERLAY_PRIORITY = { normal: 8, strong: 900 } as const

interface Props {
  states: ReadonlyMap<string, BlockState>
  selectedCode: string | null
  onPick: (id: string) => void
  elements: LabelElements
  /** 블록 홉(relations.ts — 1 이상이면 '1차' · '2차' 칩). */
  hops?: ReadonlyMap<string, number>
  overlays?: readonly OverlayLabel[]
}

/** 캔버스 위 라벨 겹(캔버스와 같은 크기, 라벨 밖은 마우스가 캔버스로 지나간다). */
export function LabelLayer({ states, selectedCode, onPick, elements, hops, overlays = [] }: Props) {
  const register = (key: string) => (element: HTMLElement | null) => {
    if (element) elements.labels.set(key, element)
    else elements.labels.delete(key)
  }
  const leader = (key: string) => (element: SVGLineElement | null) => {
    if (element) elements.leaders.set(key, element)
    else elements.leaders.delete(key)
  }
  const base = 'pointer-events-auto absolute top-0 left-0 invisible will-change-transform'
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" data-testid="ship-labels">
      <svg aria-hidden className="absolute inset-0 size-full overflow-visible text-foreground-secondary">
        {BLOCK_LAYOUT.map((place) => {
          const state = states.get(place.code)
          const strong = selectedCode === place.code || !!state?.severity
          return (
            <line
              key={place.code}
              ref={leader(place.code)}
              data-leader={place.code}
              stroke="currentColor"
              strokeWidth={strong ? 1.25 : 1}
              strokeOpacity={strong ? 0.85 : 0.55}
              style={{ visibility: 'hidden' }}
            />
          )
        })}
      </svg>
      {CONTEXT_LABELS.map((label) => (
        <span
          key={label.text}
          ref={register(`ctx:${label.text}`)}
          data-priority={0}
          className={cn(base, 'pointer-events-none text-xs whitespace-nowrap text-foreground-secondary select-none')}
        >
          {label.text}
        </span>
      ))}
      {overlays.map((overlay) => (
        <span
          key={overlay.key}
          ref={register(overlay.key)}
          data-priority={overlay.strong ? OVERLAY_PRIORITY.strong : OVERLAY_PRIORITY.normal}
          data-relation-label={overlay.key}
          className={cn(
            base,
            'pointer-events-none rounded-sm border bg-surface/90 px-1 text-xs whitespace-nowrap text-foreground select-none',
            overlay.strong ? 'border-foreground font-medium' : 'border-border-strong',
          )}
        >
          {overlay.text}
        </span>
      ))}
      {BLOCK_LAYOUT.map((place) => {
        const state = states.get(place.code)
        if (!state) return null
        const hop = hopName(hops?.get(place.code))
        const selected = selectedCode === place.code
        const priority = priorityOf(state, selected)
        const look = cn(
          base,
          'flex items-center gap-1 rounded-sm border bg-surface/95 px-1.5 py-0.5 text-xs whitespace-nowrap shadow-xs',
          state.pick ? 'cursor-pointer border-border-strong text-foreground hover:bg-hover' : 'pointer-events-none border-border text-foreground-secondary',
          state.target && 'border-2 border-foreground',
          selected && 'ring-2 ring-ring ring-offset-1 ring-offset-surface',
        )
        const body = (
          <>
            <span className="font-mono">{place.code}</span>
            {state.severity && <SeverityBadge severity={state.severity} className="h-[18px] px-1" />}
            {hop && (
              <span className="rounded-sm border border-border-strong px-1 text-xs leading-4 text-foreground-secondary" data-hop={hop}>
                {hop}
              </span>
            )}
          </>
        )
        return state.pick ? (
          <button
            key={place.code}
            ref={register(place.code)}
            data-priority={priority}
            type="button"
            className={look}
            data-block-label={place.code}
            aria-pressed={selected}
            aria-label={`${place.code} ${place.name}${state.severity ? `, 영향 ${SEVERITY_NAMES[state.severity]}` : ''}${state.target ? ', 바꾸는 부재' : ''}${hop ? `, ${hop} 영향` : ''}`}
            onClick={() => state.pick && onPick(state.pick)}
          >
            {body}
          </button>
        ) : (
          <span key={place.code} ref={register(place.code)} data-priority={priority} className={look} title={`${place.code} ${place.name} · 영향 없음`}>
            {body}
          </span>
        )
      })}
    </div>
  )
}

/** 블록 이름 툴팁(마우스를 올린 블록) — 장면이 바로 보이고 숨긴다. */
export interface TipHandle {
  show: (title: string, detail: string, x: number, y: number) => void
  hide: () => void
}

export function HoverTip({ handle }: { handle: RefObject<TipHandle | null> }) {
  const box = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLSpanElement>(null)
  const detail = useRef<HTMLSpanElement>(null)
  useImperativeHandle(
    handle,
    () => ({
      show(text, more, x, y) {
        const element = box.current
        const parent = element?.parentElement
        if (!element || !parent || !title.current || !detail.current) return
        title.current.textContent = text
        detail.current.textContent = more
        element.style.display = 'flex'
        // 커서 오른쪽 아래, 칸 밖으로 나가면 반대쪽으로
        const w = element.offsetWidth
        const h = element.offsetHeight
        const left = x + 14 + w > parent.clientWidth ? x - 14 - w : x + 14
        const top = y + 18 + h > parent.clientHeight ? y - 12 - h : y + 18
        element.style.transform = `translate(${Math.max(4, left).toFixed(0)}px, ${Math.max(4, top).toFixed(0)}px)`
      },
      hide() {
        if (box.current) box.current.style.display = 'none'
      },
    }),
    [],
  )
  return (
    <div
      ref={box}
      role="tooltip"
      className="pointer-events-none absolute top-0 left-0 z-[1100] hidden flex-col gap-0.5 rounded-sm border border-border-strong bg-surface px-2 py-1 text-xs shadow-md"
      data-testid="ship-tip"
    >
      <span ref={title} className="font-medium text-foreground" />
      <span ref={detail} className="text-foreground-secondary" />
    </div>
  )
}
