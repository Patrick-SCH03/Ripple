// 넓은 화면의 영향 지도: 그래프(위) + 근거(아래), 판이 1100px 이상(모니터)이고 그래프가 옆 배치에서도 크게 보이면 그래프 | 근거. 그래프 라이브러리와 함께
// 처음 그릴 때 따로 불러온다. 묶음 펼침 상태를 여기서 들고, 접힌 묶음 안의 엔터티를 다른 곳(팔레트·영향 목록)에서 고르면
// 그 묶음을 펼친다.
import { useCallback, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { useDefaultLayout } from 'react-resizable-panels'
import type { ImpactView } from '@/api/client'
import { EvidencePanel } from '@/components/EvidencePanel'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { MAP_LAYOUT, boundsOf, graphModel, isGroup, mapGraphHeight, mapOrientation } from '@/lib/graphModel'
import { safeStorage } from '@/lib/storage'
import { RippleFlow } from './RippleFlow'
import { useFullscreen } from './useFullscreen'

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
}

/** 판 아래 '2D 영향 지도 | 3D 배치' 띠 높이(px, MapViewSwitch) — 판 전체 상한에서 뺀다. */
const SWITCH = 46
/** 위아래 배치의 그래프 칸 최소 높이(px, 도구 막대 포함). */
const GRAPH_MIN = 240
/** 위아래 배치에서 근거 칸을 줄일 수 있는 하한(판 상한 대비) — 근거 패널 minSize 20%와 같다. */
const EVIDENCE_MIN_SHARE = 0.2

/** 판(지도 + 아래 띠) 상한: 창 높이에서 위 막대·제목·여백을 뺀 높이, 480~1000px(RipplePanel의 max-h와 같은 식). */
function frameMax(): number {
  return Math.min(1000, Math.max(480, window.innerHeight - 96))
}

interface Fit {
  orientation: 'horizontal' | 'vertical'
  /** 그래프 칸 · 근거 칸 높이(px, 위아래 배치만 — 옆 배치는 판 높이 그대로). */
  graph: number
  evidence: number
  /** 이 작업 공간 높이(px). */
  height: number
}

/**
 * 판 크기와 그래프 모양으로 고른 배치(lib/graphModel `mapOrientation`)와 높이: 처음 그리기 전에 재서 한 번 그린다(재기 전에는 null).
 * 위아래 배치는 그래프 칸을 그래프 모양에 맞춘 높이(`mapGraphHeight`)로 줄여 판 가운데 위아래 공백을 없애고, 근거 칸은 상한의
 * 34%(읽기 배율 그래프가 넘치면 20%까지 줄임)를 둔다. 그래프 모양은 묶음을 접은 처음 배치로 잰다 — 묶음을 펼칠 때마다 배치가 바뀌어 다시 그려지지 않게.
 */
function useFit(frame: RefObject<HTMLDivElement | null>, graph: { width: number; height: number }): Fit | null {
  const [fit, setFit] = useState<Fit | null>(null)
  useLayoutEffect(() => {
    const element = frame.current
    if (!element) return
    const check = () => {
      const { width } = element.getBoundingClientRect()
      const available = frameMax() - SWITCH
      const orientation = mapOrientation({ width, height: available }, graph)
      // 도구 막대는 좁으면 두 줄이 된다: 그려졌으면 실제 높이로
      const bar = element.querySelector<HTMLElement>('[data-flow-toolbar]')?.offsetHeight || MAP_LAYOUT.toolbar
      // 근거 칸은 상한의 34%. 읽기 배율(lib/graphModel MAP_READ_ZOOM)의 그래프가 그 나머지에 안 들어가면 근거 칸을 20%까지 줄여
      // 그래프 칸에 준다(왼쪽 열에 세로로 쌓인 바꾸는 부재가 아래로 잘리지 않게)
      const evidenceMax = Math.round(available * (1 - MAP_LAYOUT.graphShare))
      const evidenceMin = Math.round(available * EVIDENCE_MIN_SHARE)
      const graphHeight =
        orientation === 'vertical'
          ? mapGraphHeight(width, graph, { min: GRAPH_MIN, max: available - evidenceMin }, bar)
          : available
      const evidence = orientation === 'vertical' ? Math.max(evidenceMin, Math.min(evidenceMax, available - graphHeight)) : evidenceMax
      const next: Fit = {
        orientation,
        graph: graphHeight,
        evidence,
        height: orientation === 'vertical' ? graphHeight + evidence + 1 : available,
      }
      setFit((current) =>
        current &&
        current.orientation === next.orientation &&
        current.graph === next.graph &&
        current.evidence === next.evidence
          ? current
          : next,
      )
    }
    check()
    const resize = new ResizeObserver(check)
    resize.observe(element)
    window.addEventListener('resize', check)
    // 도구 막대가 그려지거나 줄 수가 바뀌면 다시 잰다
    const mutation = new MutationObserver(check)
    mutation.observe(element, { childList: true, subtree: true })
    return () => {
      resize.disconnect()
      mutation.disconnect()
      window.removeEventListener('resize', check)
    }
  }, [frame, graph])
  return fit
}

/** 고른 엔터티가 접힌 묶음 안에 있으면 그 묶음 ID. */
function holderOf(report: ImpactView, expanded: ReadonlySet<string>, selected: string | null): string | null {
  if (!selected || isGroup(selected)) return null
  const holder = graphModel(report, expanded).cardOf.get(selected)
  return holder && isGroup(holder) ? holder : null
}

export default function GraphWorkspace({ report, selected, onSelect }: Props) {
  // 다시 그릴 때(목록 접기·폭 전환)도 고른 엔터티가 접힌 묶음 안에 숨지 않게 처음부터 펼친다
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => {
    const holder = holderOf(report, new Set(), selected)
    return new Set(holder ? [holder] : [])
  })
  const model = useMemo(() => graphModel(report, expanded), [report, expanded])
  const groups = useMemo(() => new Map(model.cards.filter((card) => isGroup(card.id)).map((card) => [card.id, card])), [model])
  // 펼친 뒤 초점을 받을 카드(고른 묶음을 펼치면 그 묶음 카드가 사라지므로 첫 구성원으로)
  const [focusTarget, setFocusTarget] = useState<string | null>(null)
  const focused = useCallback(() => setFocusTarget(null), [])
  const expand = useCallback(
    (id: string) => {
      setExpanded((current) => new Set(current).add(id))
      if (id === selected) {
        setFocusTarget(groups.get(id)?.members[0] ?? null)
        onSelect(null)
      }
    },
    [groups, onSelect, selected],
  )
  // 전체 화면은 그래프와 근거를 함께 키운다(카드를 고르면 근거도 보이게). 고른 카드가 있으면 Esc는 고른 것부터 푼다
  const frame = useRef<HTMLDivElement>(null)
  const shape = useMemo(() => boundsOf(graphModel(report).cards), [report])
  const fit = useFit(frame, shape)
  const orientation = fit?.orientation ?? null
  const side = orientation === 'horizontal'
  // 옆 배치는 경계 위치를 기억한다. 위아래 배치는 그래프 모양에 맞춘 높이로 그리므로 기억한 비율을 쓰지 않는다
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: 'ripple.detail.map.side', storage: safeStorage })
  const canClose = useCallback(() => selected === null, [selected])
  const fullscreen = useFullscreen(frame, canClose)

  // 고른 엔터티가 바뀐 순간에만 그 묶음을 펼친다(렌더 중 상태 맞추기). '다시 묶기'를 눌러도 곧바로 다시 펼치지 않는다
  const [seen, setSeen] = useState(selected)
  if (selected !== seen) {
    setSeen(selected)
    const holder = holderOf(report, expanded, selected)
    if (holder) setExpanded((current) => new Set(current).add(holder))
  }

  return (
    <div
      ref={frame}
      className={fullscreen.overlay ? 'fixed inset-0 z-50 flex flex-col bg-surface' : 'relative min-h-0 shrink bg-surface'}
      // 판 높이 = 그래프 모양에 맞춘 높이(위아래) 또는 상한(옆). 판의 max-h를 넘으면 줄어든다(전체 화면은 화면 크기)
      style={fullscreen.full ? undefined : { height: fit?.height ?? frameMax() - SWITCH }}
      aria-label={fullscreen.full ? '영향 지도 전체 화면' : undefined}
      role={fullscreen.full ? 'region' : undefined}
    >
      {orientation && (
        <ResizablePanelGroup
          key={orientation}
          orientation={orientation}
          defaultLayout={side ? defaultLayout : undefined}
          onLayoutChanged={side ? onLayoutChanged : undefined}
        >
          <ResizablePanel id="graph" defaultSize={side ? '70%' : `${fit?.graph ?? 0}px`} minSize={side ? '45%' : '30%'}>
            <RippleFlow
              report={report}
              model={model}
              selected={selected}
              onSelect={onSelect}
              onExpand={expand}
              onCollapseAll={expanded.size > 0 ? () => setExpanded(new Set()) : null}
              focusTarget={focusTarget}
              onFocused={focused}
              full={fullscreen.full}
              onToggleFull={fullscreen.toggle}
            />
          </ResizablePanel>
          <ResizableHandle aria-label={side ? '그래프와 근거 폭 조절' : '그래프와 근거 높이 조절'} />
          {/* 위아래 배치의 근거 칸은 높이(px)를 지키고, 그래프 칸 높이가 바뀌면(폭·도구 막대 줄 수) 그래프 칸이 받는다 */}
          <ResizablePanel
            id="evidence"
            defaultSize={side ? undefined : `${fit?.evidence ?? 0}px`}
            minSize={side ? '340px' : '20%'}
            groupResizeBehavior={side ? 'preserve-relative-size' : 'preserve-pixel-size'}
            style={{ overflow: 'auto' }}
          >
            <EvidencePanel report={report} selected={selected} onSelect={onSelect} groups={groups} onExpand={expand} />
          </ResizablePanel>
        </ResizablePanelGroup>
      )}
    </div>
  )
}
