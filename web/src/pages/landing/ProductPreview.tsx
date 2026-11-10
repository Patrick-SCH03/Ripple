// 문제 절의 제품 미리보기: 업무 화면의 상세처럼 '파급 그림 | 판정·핵심 수치'. 값은 엔진 출력(example.json, 합성 데이터).
// 핵심 수치는 업무 화면 판단 요약과 같은 순서(추가 공수 · 추가 재료비 → 총변경비용 → 결정 기한).
// 그림은 화면에 들어올 때 시작하고(휴대폰에서 아래에 있어도 보기 전에 끝나 버리지 않게), 추가 공수(MH)는 그림이 다 나타난 뒤
// 0부터 올라간다. 움직임 줄이기면 바로 정지 그림·최종값. '다시 보기'는 처음부터 다시 그린다.
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { formatHours } from '@/lib/costSplit'
import { formatDay } from '@/lib/format'
import { SHOWCASE, SHOWCASE_TODAY, costText, verdictText } from './example'
import { prefersReducedMotion, useInView } from './motion'
import { RippleList, RippleSvg } from './RippleDiagram'

const COUNT_DELAY_MS = 2000
const COUNT_MS = 900
const SETTLE_MS = COUNT_DELAY_MS + COUNT_MS + 200 // 그림·금액이 다 끝난 뒤 정지 그림으로

/** 0 → 값으로 올라가는 수(글자만 바뀜, 읽기 프로그램에는 최종값만). started 전에는 0에 머문다. */
function useCountUp(target: number, run: number, started: boolean): number {
  const [value, setValue] = useState(() => (prefersReducedMotion() ? target : 0))
  useEffect(() => {
    if (prefersReducedMotion() || !started) return
    let frame = 0
    const begin = performance.now() + COUNT_DELAY_MS
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - begin) / COUNT_MS))
      setValue(Math.round(target * (1 - (1 - t) ** 3)))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, run, started])
  return value
}

function VerdictPanel({ run, started }: { run: number; started: boolean }) {
  const text = verdictText(SHOWCASE_TODAY)
  const cost = costText(SHOWCASE_TODAY)
  const hours = useCountUp(SHOWCASE.cost.labor_hours.value, run, started)
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-surface p-4 lg:p-5" data-testid="showcase-verdict">
      <div>
        <p className="text-sm text-foreground-secondary">판정</p>
        <p className="mt-1 inline-flex items-center gap-1.5 rounded-sm border border-danger/50 px-2 py-0.5 text-sm font-semibold text-danger">
          <AlertTriangle aria-hidden className="size-4" />
          {text.label}
        </p>
        <ul className="mt-2 flex flex-col gap-0.5 text-sm text-foreground-secondary">
          {text.reasons.map((reason) => (
            <li key={reason}>· {reason}</li>
          ))}
        </ul>
      </div>
      {/* 업무 화면 판단 요약과 같은 순서: 첫 줄 총변경비용 · 추가 공수 · 추가 재료비, 다음 결정 기한 */}
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
        <div className="rounded-md border border-border-strong p-3">
          <dt className="text-sm text-foreground-secondary">총변경비용</dt>
          <dd className="text-key font-semibold tabular-nums">{cost.total}</dd>
        </div>
        <div className="rounded-md border border-border p-3">
          <dt className="text-sm text-foreground-secondary">추가 공수</dt>
          <dd className="flex flex-wrap items-baseline gap-x-1.5 tabular-nums">
            <span className="text-key font-semibold" aria-hidden>
              {formatHours(hours)} MH
            </span>
            <span className="sr-only">{cost.hours}</span>
            <span className="text-sm text-foreground-secondary">≈ {cost.laborMoney}</span>
          </dd>
        </div>
        <div className="rounded-md border border-border p-3">
          <dt className="text-sm text-foreground-secondary">추가 재료비</dt>
          <dd className="text-key font-semibold tabular-nums">{cost.material}</dd>
          {cost.ordered !== null && <dd className="text-sm font-semibold">이미 발주 {cost.ordered}건</dd>}
        </div>
        {text.deadline && (
          <div className="rounded-md border border-border p-3">
            <dt className="text-sm text-foreground-secondary">결정 기한</dt>
            <dd className="text-key font-semibold">{text.dDay}</dd>
            <dd className="text-sm text-foreground-secondary">{text.deadline}까지 확정</dd>
          </div>
        )}
      </dl>
      {text.later && <p className="rounded-sm border border-warning/50 px-3 py-2 text-sm text-warning">{text.later}</p>}
      {text.exit && <p className="text-sm text-foreground-secondary">구역 출구 예상 지연 · {text.exit}</p>}
    </div>
  )
}

export function ProductPreview() {
  const [ref, started] = useInView<HTMLElement>('0px 0px -15% 0px')
  const [run, setRun] = useState(0)
  const [settled, setSettled] = useState<number | null>(() => (prefersReducedMotion() ? 0 : null))
  useEffect(() => {
    if (prefersReducedMotion() || !started) return
    const timer = window.setTimeout(() => setSettled(run), SETTLE_MS)
    return () => window.clearTimeout(timer)
  }, [run, started])
  const animate = settled !== run && !prefersReducedMotion()
  return (
    <figure
      ref={ref}
      className={`rp-card overflow-hidden rounded-[20px] border border-border bg-canvas ${started ? '' : 'rp-paused'}`}
      data-testid="product-preview"
    >
      <figcaption className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface px-4 py-3">
        <span className="font-mono text-sm">{SHOWCASE.ecn_id}</span>
        <span className="min-w-0 text-sm font-semibold">{SHOWCASE.title}</span>
        <span className="text-xs text-foreground-secondary">합성 데이터 · 예시 기준일 {formatDay(SHOWCASE_TODAY.as_of)}</span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setRun((n) => n + 1)}>
          <RotateCcw aria-hidden />
          다시 보기
        </Button>
      </figcaption>
      <div className="grid gap-4 p-4 sm:gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:p-8">
        <div key={run} className="min-w-0 self-start">
          <div className="hidden sm:block">
            <RippleSvg animate={animate} />
          </div>
          <div className="sm:hidden">
            <RippleList animate={animate} />
          </div>
        </div>
        <VerdictPanel key={`v-${run}`} run={run} started={started} />
      </div>
    </figure>
  )
}
