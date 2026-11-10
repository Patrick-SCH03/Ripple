// 영향 지도(상세의 핵심 수치 바로 아래): 넓은 화면은 그래프 작업 공간(그래프 + 근거), 좁은 화면은 들여쓴 영향 목록 + 근거
// (DESIGN.md 7절). 고르면 초점을 근거 제목으로, 전체 요약으로 돌아오면 고르기 전 자리(그래프 카드·목록 줄)로 돌려준다.
// 지도 아래 띠에서 '2D 영향 지도 | 3D 배치'를 고른다(3D는 three 묶음을 그때 불러옴, WebGL이 없으면 2D 유지 + 안내).
// 좁은 화면은 목록 아래 '3D 배치 보기' 단추 하나로 전체 화면 대화상자에서만 연다.
import { lazy, type RefObject, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { ImpactView } from '@/api/client'
import { Box } from 'lucide-react'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { EvidencePanel } from '@/components/EvidencePanel'
import { MapViewSwitch, Unavailable } from '@/components/graph3d/MapViewSwitch'
import { hasWebGL, type MapView } from '@/components/graph3d/webgl'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { ImpactOutline } from './ImpactOutline'

// 그래프 라이브러리는 크므로 넓은 화면에서 처음 그릴 때 불러온다(좁은 화면은 들여쓴 목록만 쓴다)
const GraphWorkspace = lazy(() => import('@/components/graph/GraphWorkspace'))
// three(3D 배치)는 3D를 열 때만 불러온다
const Ship3DWorkspace = lazy(() => import('@/components/graph3d/Ship3DWorkspace'))
const Ship3DSheet = lazy(() => import('@/components/graph3d/Ship3DSheet'))

const NO_WEBGL = '3D 보기를 쓸 수 없는 브라우저 · 2D 영향 지도 유지'
/** 고른 보기(이 창이 떠 있는 동안만 — 다른 설계변경을 열어도 유지, 새로 고침이면 2D). */
let lastView: MapView = '2d'

interface Props {
  view: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
  /** 좁은 화면: 그래프 대신 들여쓴 목록, 근거는 그 아래로 이어서. */
  compact: boolean
  /** 바깥(명령 팔레트)에서 근거 열기를 요청할 때마다 늘어나는 번호. 바뀌면 같은 엔터티여도 근거 제목으로 초점. */
  focusRequest: number
}

export function RipplePanel({ view, selected, onSelect, compact, focusRequest }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const evidence = useRef<HTMLDivElement>(null)
  const previous = useRef<string | null>(null)
  const origin = useRef<HTMLElement | null>(null)
  /** 근거 제목으로 옮길 초점이 남아 있음(제목이 아직 안 그려졌으면 나타날 때 옮긴다). */
  const pending = useRef(false)
  const lastRequest = useRef(focusRequest)

  useEffect(() => {
    const before = previous.current
    previous.current = selected
    const requested = focusRequest !== lastRequest.current
    lastRequest.current = focusRequest
    const container = root.current
    if (!container) return
    if (requested && selected) pending.current = true
    // 좁은 화면에서는 근거가 목록 아래에 있으므로, 고르거나 근거 열기를 요청하면(같은 엔터티를 다시 골라도) 근거로
    // 내려간다. scrollIntoView는 바깥 칸까지 밀어 올리므로 상세의 스크롤 칸만 움직인다
    const scroller = container.closest<HTMLElement>('[data-detail-scroll]')
    if ((before !== selected || requested) && compact && selected && scroller && evidence.current) {
      const top = evidence.current.getBoundingClientRect().top - scroller.getBoundingClientRect().top
      scroller.scrollTo({ top: scroller.scrollTop + top })
    }
    if (before !== selected) {
      // 고른 줄이 사라지거나 화면 밖으로 밀리므로 초점을 근거 제목으로 옮기고, 전체 요약으로 돌아오면
      // 고르기 전 초점 자리(그래프 카드·목록 줄)로 돌려준다. 그 자리가 사라졌으면 그 엔터티의 카드 → 목록 줄.
      // 초점이 다른 칸(요청 입력 등)에 있으면 건드리지 않는다
      const active = document.activeElement
      const ours = !active || active === document.body || container.contains(active) || active.closest('[role="dialog"]')
      pending.current = Boolean(selected && (ours || requested))
      if (selected && ours && !before && active instanceof HTMLElement && container.contains(active)) {
        origin.current = active
      }
      if (!selected && before && ours) {
        const id = CSS.escape(before)
        const back =
          (origin.current?.isConnected ? origin.current : null) ??
          container.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`) ??
          container.querySelector<HTMLElement>(`[data-entity-row="${id}"]`)
        origin.current = null
        back?.focus()
      }
    }
    if (!pending.current) return
    // 그래프 묶음(지연 로딩)이 근거 제목을 아직 안 그렸을 수 있으므로
    // 나타날 때까지 기다린다(최대 5초). 그동안 사용자가 이 칸 밖의 입력 칸으로 옮겼으면 초점을 뺏지 않는다.
    // 남은 일은 pending에 두므로 개발 모드의 효과 두 번 실행(정리 → 다시 실행)에도 이어서 기다린다
    const typingElsewhere = () => {
      const now = document.activeElement
      return (
        now instanceof HTMLElement &&
        !container.contains(now) &&
        !now.closest('[role="dialog"]') &&
        (now.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(now.tagName))
      )
    }
    /** 끝났으면(초점을 옮겼거나 그만둘 때) true. */
    const focusTitle = () => {
      const title = typingElsewhere() ? null : container.querySelector<HTMLElement>('[data-evidence-title]')
      title?.focus({ preventScroll: compact })
      if (title || typingElsewhere()) pending.current = false
      return !pending.current
    }
    if (focusTitle()) return
    const observer = new MutationObserver(() => {
      if (focusTitle()) stop()
    })
    const timer = window.setTimeout(() => {
      pending.current = false
      stop()
    }, 5000)
    const stop = () => {
      observer.disconnect()
      window.clearTimeout(timer)
    }
    observer.observe(container, { childList: true, subtree: true })
    return stop
  }, [compact, selected, focusRequest])

  const [mapView, setMapView] = useState<MapView>(() => (lastView === '3d' && hasWebGL() ? '3d' : '2d'))
  const [notice, setNotice] = useState<string | null>(null)
  const chooseView = (next: MapView) => {
    const usable = next === '2d' || hasWebGL()
    setNotice(usable ? null : NO_WEBGL)
    lastView = usable ? next : '2d'
    setMapView(lastView)
  }
  const fallBack = useCallback((message: string) => {
    setNotice(message)
    lastView = '2d'
    setMapView('2d')
  }, [])
  const failed = useCallback(() => fallBack('3D 배치 불러오기 실패 · 2D 영향 지도 유지'), [fallBack])

  if (compact) {
    return (
      <div ref={root}>
        <ImpactOutline report={view} selected={selected} onSelect={onSelect} />
        <CompactShip view={view} selected={selected} onSelect={onSelect} evidence={evidence} />
        <div ref={evidence} className="border-t border-border">
          <EvidencePanel report={view} selected={selected} onSelect={onSelect} list={false} />
        </div>
      </div>
    )
  }
  return (
    // 판 높이 상한은 창 높이에 맞춘다(모니터에서 지도 제목까지 내리면 판이 화면에 꼭 들어오게): 위 막대·제목·여백을 뺀 높이, 480~1000px.
    // 2D는 그래프 모양에 맞춰 그 안에서 줄어든다(GraphWorkspace — 옆으로 긴 사슬이 높은 판 가운데 작게 떠 위아래가 비지 않게), 3D는 상한 그대로
    <div
      ref={root}
      className={cn(
        'flex flex-col overflow-clip rounded-md border border-border',
        mapView === '3d' ? 'h-[clamp(480px,calc(100dvh_-_6rem),1000px)]' : 'max-h-[clamp(480px,calc(100dvh_-_6rem),1000px)]',
      )}
    >
      {mapView === '3d' ? (
        <ErrorBoundary key={`3d:${view.analysis_id}`} fallback={<Unavailable onUnavailable={failed} />}>
          <Suspense fallback={<p className="p-6 text-sm text-foreground-secondary">3D 배치 불러오는 중…</p>}>
            <Ship3DWorkspace report={view} selected={selected} onSelect={onSelect} />
          </Suspense>
        </ErrorBoundary>
      ) : (
        <ErrorBoundary key={view.analysis_id} fallback={<GraphFailed />}>
          <Suspense fallback={<p className="p-6 text-sm text-foreground-secondary">그래프를 불러오는 중…</p>}>
            <GraphWorkspace report={view} selected={selected} onSelect={onSelect} />
          </Suspense>
        </ErrorBoundary>
      )}
      <MapViewSwitch view={mapView} onView={chooseView} notice={notice} />
    </div>
  )
}

interface CompactShipProps {
  view: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
  evidence: RefObject<HTMLDivElement | null>
}

/** 좁은 화면: 목록 아래 단추 하나 → 전체 화면 대화상자의 3D 배치. '근거 보기'로 닫으면 목록 아래 근거 제목으로. */
function CompactShip({ view, selected, onSelect, evidence }: CompactShipProps) {
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const toEvidence = useRef(false)
  const close = useCallback((message: string) => {
    setNotice(message)
    setOpen(false)
  }, [])
  const failed = useCallback(() => close('3D 배치 불러오기 실패 · 영향 목록 유지'), [close])
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-3 py-2">
      <Button
        variant="outline"
        className="h-11"
        data-graph-toggle="3d"
        onClick={() => {
          if (hasWebGL()) {
            setNotice(null)
            setOpen(true)
          } else setNotice(NO_WEBGL)
        }}
      >
        <Box aria-hidden />
        3D 배치 보기
      </Button>
      {notice && (
        <p role="status" className="text-xs text-warning">
          {notice}
        </p>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          showCloseButton={false}
          aria-describedby={undefined}
          className="top-0 left-0 flex h-dvh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 ring-0 sm:max-w-none"
          onCloseAutoFocus={(event) => {
            if (!toEvidence.current) return
            // 근거 보기: 닫은 뒤 상세 스크롤 칸만 근거까지 내리고 근거 제목으로 초점
            toEvidence.current = false
            event.preventDefault()
            const target = evidence.current
            const scroller = target?.closest<HTMLElement>('[data-detail-scroll]')
            if (target && scroller) {
              scroller.scrollTo({ top: scroller.scrollTop + target.getBoundingClientRect().top - scroller.getBoundingClientRect().top })
            }
            target?.querySelector<HTMLElement>('[data-evidence-title]')?.focus({ preventScroll: true })
          }}
        >
          <ErrorBoundary key={view.analysis_id} fallback={<Unavailable onUnavailable={failed} />}>
            <Suspense fallback={<p className="p-6 text-sm text-foreground-secondary">3D 배치 불러오는 중…</p>}>
              <Ship3DSheet
                report={view}
                selected={selected}
                onSelect={onSelect}
                onEvidence={() => {
                  toEvidence.current = true
                  setOpen(false)
                }}
              />
            </Suspense>
          </ErrorBoundary>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** 그래프 묶음을 못 불러왔을 때(새 배포로 파일 이름이 바뀐 경우 등): 화면 전체 대신 이 칸만, 새로 고침으로 회복. */
function GraphFailed() {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 p-6 text-sm">
      <p>영향 지도 불러오기 실패 · 새로 고침으로 다시 불러오기</p>
      <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
        새로 고침
      </Button>
    </div>
  )
}
