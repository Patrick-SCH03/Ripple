// 3D 배치 위 막대(캔버스 밖): 범례(2D 영향 지도와 같은 문구·색) · 시점(전체·화물창·선미·선수) · 시점 초기화 · 전체 화면.
import { Expand, LocateFixed, MoveRight, Pause, Play, Shrink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { VIEWS, type ViewName } from './layout'

interface Props {
  current: ViewName
  onView: (name: ViewName) => void
  onReset: () => void
  /** 고른 블록이 있나(있으면 범례에 '이웃 블록 이음'). */
  linking: boolean
  /** 강조한 용접 이음면(바꾸는 블록·영향이 건너간 이웃)이 있나(있으면 범례에 '용접 이음면'). */
  flowing?: boolean
  /** 블록 사이 관계 화살표가 있나(있으면 범례에 '영향 방향'). */
  directed?: boolean
  /** 맥동 켜짐 여부(맥동할 영향 블록이 없으면 null — 단추를 내지 않음). */
  motion: boolean | null
  onMotion: () => void
  full: boolean
  onToggleFull?: () => void
  /** 터치 높이(좁은 화면의 전체 화면 보기). */
  touch?: boolean
}

const SWATCHES: { label: string; className: string }[] = [
  { label: '높음', className: 'bg-danger' },
  { label: '보통', className: 'bg-warning' },
  { label: '낮음', className: 'bg-primary' },
  { label: '영향 없음', className: 'border border-border-strong bg-border-strong/40' },
]

export function ShipToolbar({ current, onView, onReset, linking, flowing = false, directed = false, motion, onMotion, full, onToggleFull, touch = false }: Props) {
  const size = touch ? 'h-11 px-3' : undefined
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-3 py-1.5">
      <ul aria-label="범례" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground-secondary">
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm border-2 border-foreground" />
          바꾸는 부재
        </li>
        {SWATCHES.map((swatch) => (
          <li key={swatch.label} className="flex items-center gap-1.5">
            <span aria-hidden className={cn('size-3 rounded-sm', swatch.className)} />
            {swatch.label}
          </li>
        ))}
        {directed && (
          <li className="flex items-center gap-1.5">
            <MoveRight aria-hidden className="size-4 text-foreground" />
            영향 방향
          </li>
        )}
        {flowing && (
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="w-4 border-t-[3px] border-foreground" />
            용접 이음면
          </li>
        )}
        {linking && (
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-4 rounded-[2px] border-2 border-primary bg-primary/40" />
            이웃 블록 이음면
          </li>
        )}
      </ul>
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        <div role="group" aria-label="시점" className="flex overflow-hidden rounded-md border border-border-strong">
          {VIEWS.map((view, i) => (
            <button
              key={view.name}
              type="button"
              aria-pressed={current === view.name}
              onClick={() => onView(view.name)}
              data-testid={`ship-view-${view.name}`}
              className={cn(
                'h-9 px-2.5 text-sm font-medium transition-colors focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-ring',
                touch && 'h-11 px-3',
                i > 0 && 'border-l border-border-strong',
                current === view.name ? 'bg-secondary text-foreground' : 'bg-surface text-foreground-secondary hover:bg-hover',
              )}
            >
              {view.label}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" className={size} onClick={onReset} data-testid="ship-view-reset">
          <LocateFixed aria-hidden />
          시점 초기화
        </Button>
        {motion !== null && (
          // 좁은 화면(터치)은 아이콘만 — 시점 단추와 한 줄에 들어가게(이름은 aria-label·title)
          <Button
            variant="outline"
            size="sm"
            className={touch ? 'size-11 px-0' : undefined}
            onClick={onMotion}
            data-testid="ship-motion"
            aria-label={touch ? (motion ? '움직임 멈춤' : '움직임 켜기') : undefined}
            title={touch ? (motion ? '움직임 멈춤' : '움직임 켜기') : undefined}
          >
            {motion ? <Pause aria-hidden /> : <Play aria-hidden />}
            {!touch && (motion ? '움직임 멈춤' : '움직임 켜기')}
          </Button>
        )}
        {onToggleFull && (
          <Button variant="outline" size="sm" className={size} onClick={onToggleFull} aria-pressed={full}>
            {full ? <Shrink aria-hidden /> : <Expand aria-hidden />}
            {full ? '전체 화면 끝내기' : '전체 화면'}
          </Button>
        )}
      </div>
    </div>
  )
}
