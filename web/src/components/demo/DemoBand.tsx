// 시연 안내 띠: 화면 아래 가운데에 떠서 '시연 · 2/7 — 무엇을 하는지'(명사형)와 '멈추기'(Esc)를 보인다. 아래 얇은 선이
// 진행 정도. 끝나면 '시연 끝 — 처음 화면으로 돌아옴', 막히면 '여기서 멈춤 — 화면 확인 필요'를 잠깐 남기고 닫힌다.
import { CircleCheck, Play, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { bandLabel, bandText, type DemoPhase } from '@/lib/demo'
import { cn } from '@/lib/utils'
import type { DemoState } from './useDemoRunner'

interface Props {
  state: DemoState
  bandRef: RefObject<HTMLDivElement | null>
  onStop: () => void
}

/** 상태마다 아이콘과 그 색. */
const LOOK: Record<Exclude<DemoPhase, 'idle'>, { Icon: LucideIcon; tone: string }> = {
  running: { Icon: Play, tone: 'text-primary' },
  stuck: { Icon: TriangleAlert, tone: 'text-warning' },
  done: { Icon: CircleCheck, tone: 'text-success' },
}

export function DemoBand({ state, bandRef, onStop }: Props) {
  const { phase } = state
  if (phase === 'idle') return null
  const running = phase === 'running'
  const stuck = phase === 'stuck'
  const { Icon, tone } = LOOK[phase]
  const text = bandText(phase, state.caption)
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 bottom-6 z-60 flex justify-center px-4">
      <div
        ref={bandRef}
        data-testid="demo-band"
        data-phase={phase}
        className="pointer-events-auto relative flex w-full max-w-3xl items-center gap-3 overflow-hidden rounded-md border border-border bg-surface py-2.5 pr-2.5 pl-4 shadow-lg"
      >
        <Icon aria-hidden className={cn('size-4 shrink-0', tone)} />
        <p role="status" aria-live="polite" className={cn('min-w-0 flex-1 text-md', stuck && 'text-warning')}>
          {running && (
            <>
              <span className="font-semibold text-primary tabular-nums">
                {state.n > 0 ? bandLabel(state.n, state.total) : '시연'}
              </span>
              <span aria-hidden className="text-foreground-secondary">
                {' — '}
              </span>
            </>
          )}
          {text}
        </p>
        <Button size="sm" variant="outline" onClick={onStop} data-testid="demo-stop" aria-keyshortcuts="Escape">
          {running ? '멈추기' : '닫기'}
          <kbd className="rounded-sm border border-border bg-muted px-1 font-sans text-xs text-foreground-secondary">Esc</kbd>
        </Button>
        {running && state.total > 0 && (
          <span
            aria-hidden
            className="absolute bottom-0 left-0 h-0.5 bg-primary transition-[width] duration-500"
            style={{ width: `${(state.n / state.total) * 100}%` }}
          />
        )}
      </div>
    </div>,
    document.body,
  )
}
