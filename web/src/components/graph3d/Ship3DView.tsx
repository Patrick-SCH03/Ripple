// 3D 배치 보기 한 칸: 위 막대 + 장면 + 아래 안내(가상 배치 표시 · 배치 정보 없는 블록 목록).
// 블록 상태는 2D와 같은 분석 결과에서(blocks.ts), 고르기는 2D와 같은 selected/onSelect.
// 3D 밖(영향 목록·근거 패널·명령 팔레트)에서 엔터티를 고르면 그 블록으로 날아가 맞추고 잠깐 강조한다(focus.ts — 블록을 정할 수
// 없으면 카메라를 두고 관련 블록 강조 또는 '배치 위치 없음'). 3D에서 블록을 눌러 고른 것은 카메라를 그대로 둔다.
import { type ReactNode, useMemo, useRef, useState } from 'react'
import type { ImpactView } from '@/api/client'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import { safeStorage } from '@/lib/storage'
import { blockStates, initialView, portSide } from './blocks'
import { selectedBlock } from './focus'
import { ADJACENCY, type ViewName, jointOf } from './layout'
import { createLabelElements } from './labelPlace'
import { focusPath, relationPlan, seamPlan } from './relations'
import { type ExtraAnchor, HoverTip, LabelLayer, type OverlayLabel, type TipHandle } from './ShipLabels'
import { arrowShapes, seamShape } from './relationShapes'
import { type SceneRelations, ShipCanvas, type ViewRequest } from './ShipScene'
import { ShipToolbar } from './ShipToolbar'
import { useOutsidePick } from './useOutsidePick'
import { wavePlan } from './wave'

/** 움직임 설정 키 — 2D 영향 지도(RippleFlow)의 '움직임 멈춤/켜기'와 같은 값을 쓴다. */
const MOTION = 'ripple.map.motion'

function initialMotion(): boolean {
  const saved = safeStorage.getItem(MOTION)
  if (saved === 'on' || saved === 'off') return saved === 'on'
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
  full: boolean
  onToggleFull?: () => void
  touch?: boolean
  /** 장면 아래에 붙일 것(좁은 화면: 고른 블록 요약). */
  footer?: ReactNode
}

export function Ship3DView({ report, selected, onSelect, full, onToggleFull, touch = false, footer }: Props) {
  const { placed, unplaced } = useMemo(() => blockStates(report), [report])
  const start = useMemo(() => initialView(placed), [placed])
  const mirror = useMemo(() => portSide(placed), [placed])
  const [view, setView] = useState<ViewRequest>({ name: start, seq: 0, mirror })
  const selectedCode = useMemo(() => selectedBlock(report, selected), [report, selected])
  const related = useMemo(() => relationPlan(report, placed), [report, placed])
  const plan = useMemo(() => wavePlan(report, placed, ADJACENCY, related.hops), [report, placed, related])
  const arrows = useMemo(() => arrowShapes(related.links), [related])
  const seams = useMemo(() => seamPlan(plan.flows, placed, ADJACENCY, (a, b) => jointOf(a, b) !== undefined), [plan, placed])
  // 초점 모드: 고른 블록까지 오는 관계 화살표만 남기고 경로 밖 블록·화살표는 흐리게(고르기를 풀면 복귀)
  const focus = useMemo(() => (selectedCode ? focusPath(related, selectedCode) : null), [related, selectedCode])
  const relations = useMemo<SceneRelations>(() => {
    const labels: OverlayLabel[] = []
    const anchors: ExtraAnchor[] = []
    for (const arrow of arrows) {
      if (focus && !focus.links.has(arrow.link.key)) continue
      labels.push({ key: `rel:${arrow.link.key}`, text: arrow.link.label, strong: focus !== null })
      anchors.push({ key: `rel:${arrow.link.key}`, at: arrow.mid })
    }
    // 고른 블록의 용접 이음면에만 이름표(늘 띄우면 라벨이 겹친다)
    for (const seam of seams) {
      if (!selectedCode || (seam.a !== selectedCode && seam.b !== selectedCode)) continue
      const shape = seamShape(seam.a, seam.b)
      if (!shape) continue
      labels.push({ key: `seam:${seam.key}`, text: '용접 이음면', strong: false })
      anchors.push({ key: `seam:${seam.key}`, at: shape.center })
    }
    return { arrows, seams, focus, anchors, labels }
  }, [arrows, seams, focus, selectedCode])
  const box = useRef<HTMLDivElement>(null)
  const [labels] = useState(createLabelElements)
  const tip = useRef<TipHandle>(null)
  const [motion, setMotion] = useState(initialMotion)
  const pulsing = useMemo(() => [...placed.values()].some((state) => state.severity !== null), [placed])
  const { fly, flash, notice, pick } = useOutsidePick(report, selected, onSelect)

  // 휠: 캔버스 위에서는 커서 쪽으로 확대·축소(ShipControls — 거리 상한·하한), 캔버스 밖에서는 페이지 스크롤 그대로.
  // 3D는 판 안에서 직접 돌려 보는 그림이라 2D 지도(Ctrl+휠)와 달리 휠을 바로 쓴다(11-03 사용자 요청)

  const go = (name: ViewName) => setView((current) => ({ name, seq: current.seq + 1, mirror }))

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ShipToolbar
        current={view.name}
        onView={go}
        onReset={() => go(start)}
        linking={selectedCode !== null}
        flowing={seams.length > 0}
        directed={arrows.length > 0}
        motion={pulsing ? motion : null}
        onMotion={() =>
          setMotion((on) => {
            safeStorage.setItem(MOTION, on ? 'off' : 'on')
            return !on
          })
        }
        full={full}
        onToggleFull={onToggleFull}
        touch={touch}
      />
      <div
        ref={box}
        className="relative isolate min-h-0 flex-1 touch-none"
        data-testid="ship-3d"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && selected) {
            event.stopPropagation()
            onSelect(null)
          }
        }}
      >
        <ShipCanvas
          states={placed}
          selectedCode={selectedCode}
          onPick={pick}
          onClear={() => onSelect(null)}
          view={view}
          full={full}
          labels={labels}
          tip={tip}
          motion={motion}
          plan={plan}
          fly={fly}
          flash={flash}
          relations={relations}
        />
        <LabelLayer states={placed} selectedCode={selectedCode} onPick={pick} elements={labels} hops={related.hops} overlays={relations.labels} />
        <HoverTip handle={tip} />
        {/* 블록을 정할 수 없는 엔터티를 골랐을 때의 짧은 안내(명사형) */}
        <p role="status" className="pointer-events-none absolute top-2 left-3 z-40 max-w-[calc(100%-1.5rem)]">
          {notice && (
            <span className="rounded-sm border border-border-strong bg-surface/95 px-2 py-0.5 text-sm text-foreground" data-testid="ship-notice">
              {notice}
            </span>
          )}
        </p>
        <p className="pointer-events-none absolute bottom-2 left-3 z-40 max-w-[calc(100%-1.5rem)] rounded-sm bg-surface/90 px-1.5 text-xs text-foreground-secondary">
          {/* 실제 도면이 아님을 밝히는 짧은 표지만 — 치수·조작 안내는 영향 범위 머리 ⓘ(mapUse), 터치 조작은 전체 화면에서만 여기 */}
          가상 배치
          {touch && ' · 한 손가락 회전 · 두 손가락 확대'}
        </p>
      </div>
      {unplaced.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-t border-border px-3 py-1.5 text-xs" data-testid="ship-unplaced">
          <span className="text-foreground-secondary">배치 정보 없는 블록 {unplaced.length}개</span>
          {unplaced.map((state) =>
            state.pick ? (
              <button
                key={state.blockId}
                type="button"
                onClick={() => state.pick && pick(state.pick)}
                className="inline-flex items-center gap-1 rounded-sm border border-border-strong px-1.5 py-0.5 hover:bg-hover"
                aria-pressed={selected !== null && state.members.includes(selected)}
              >
                <span className="font-mono">{state.blockId}</span>
                {state.severity && <SeverityBadge severity={state.severity} className="h-[18px] px-1" />}
              </button>
            ) : (
              <span key={state.blockId} className="font-mono">
                {state.blockId}
              </span>
            ),
          )}
        </div>
      )}
      {footer}
    </div>
  )
}
