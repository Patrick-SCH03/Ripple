// 영향 지도 위 막대(캔버스 밖 — 카드를 가리지 않게): 범례 · 주요 경로만 · 움직임 멈춤/켜기 · 다시 묶기 · 다시 보기 ·
// 맞춤 보기(읽기 하한 배율) · 전체 보기(넘칠 때만 — 하한 없이 한눈에) · 전체 화면.
import { Expand, ListCollapse, Maximize2, Pause, Play, RotateCcw, Route, Scan, Shrink } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  /** 주요 경로 간선·카드가 있나(없으면 범례 줄과 주요 경로 단추를 내지 않는다). */
  mainLinks: boolean
  mainCards: boolean
  motion: boolean
  onMotion: () => void
  focusMain: boolean
  onFocusMain: () => void
  onCollapseAll: (() => void) | null
  onReplay: () => void
  onFit: () => void
  /** 읽기 하한 때문에 그래프가 판에 다 들어오지 않을 때만: 하한 없는 맞춤으로 전체를 한눈에. */
  onWhole?: () => void
  full: boolean
  onToggleFull?: () => void
}

export function FlowToolbar({
  mainLinks,
  mainCards,
  motion,
  onMotion,
  focusMain,
  onFocusMain,
  onCollapseAll,
  onReplay,
  onFit,
  onWhole,
  full,
  onToggleFull,
}: Props) {
  return (
    <div data-flow-toolbar className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-1.5">
      <ul aria-label="범례" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground-secondary">
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border-2 border-foreground" />
          바꾸는 부재
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border-2 border-danger" />
          높음
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border-2 border-warning" />
          보통
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border-2 border-primary" />
          낮음
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="w-4 border-t-2 border-dashed border-primary" />
          변경으로 생김
        </li>
        {mainLinks && (
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="w-4 border-t-2 border-dashed border-danger" />
            주요 경로
          </li>
        )}
      </ul>
      <div className="ml-auto flex flex-wrap gap-1.5">
        {mainCards && (
          <Button
            variant={focusMain ? 'secondary' : 'outline'}
            size="sm"
            onClick={onFocusMain}
            aria-pressed={focusMain}
            title="가장 심각한 영향까지의 경로만 진하게"
            data-testid="map-focus-main"
          >
            <Route aria-hidden />
            주요 경로만
          </Button>
        )}
        {mainCards && (
          <Button variant="outline" size="sm" onClick={onMotion} data-testid="map-motion">
            {motion ? <Pause aria-hidden /> : <Play aria-hidden />}
            {motion ? '움직임 멈춤' : '움직임 켜기'}
          </Button>
        )}
        {onCollapseAll && (
          <Button variant="outline" size="sm" onClick={onCollapseAll}>
            <ListCollapse aria-hidden />
            다시 묶기
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={onReplay}>
          <RotateCcw aria-hidden />
          다시 보기
        </Button>
        <Button variant="outline" size="sm" onClick={onFit}>
          <Maximize2 aria-hidden />
          맞춤 보기
        </Button>
        {onWhole && (
          <Button variant="outline" size="sm" onClick={onWhole} title="그래프 전체를 한 화면에(글자 작아짐)" data-testid="map-whole">
            <Scan aria-hidden />
            전체 보기
          </Button>
        )}
        {onToggleFull && (
          <Button variant="outline" size="sm" onClick={onToggleFull} aria-pressed={full}>
            {full ? <Shrink aria-hidden /> : <Expand aria-hidden />}
            {full ? '전체 화면 끝내기' : '전체 화면'}
          </Button>
        )}
      </div>
    </div>
  )
}
