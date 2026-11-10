// 바뀐 점 띠(가정 계산 전후, lib/compare.ts): 보류 적용·빼기나 대안으로 다시 분석했을 때 상세 맨 위에 판정·총비용·
// 마감일·일정 지연의 전 → 후를 보인다. '되돌리기'는 다시 계산하지 않고 바로 전 결과로 돌아간다.
// 나아짐·나빠짐은 색만이 아니라 아이콘과 읽기용 글자로도 전한다(DESIGN.md 3절).
import { ArrowRight, CircleCheck, Minus, TriangleAlert, Undo2, X, type LucideIcon } from 'lucide-react'
import type { AnalysisResult } from '@/api/client'
import { Button } from '@/components/ui/button'
import { changeHeadline, compareResults, type Direction } from '@/lib/compare'
import type { Comparison } from '@/state/useAnalysisSession'

const LOOK: Record<Direction, { tone: string; icon: LucideIcon; spoken: string }> = {
  better: { tone: 'text-success', icon: CircleCheck, spoken: '나아짐' },
  worse: { tone: 'text-danger', icon: TriangleAlert, spoken: '나빠짐' },
  same: { tone: 'text-foreground-secondary', icon: Minus, spoken: '같음' },
}

interface Props {
  comparison: Comparison
  result: AnalysisResult
  onRestore: () => void
  onDismiss: () => void
  /** 좁은 화면·태블릿이면 터치 높이(44px, DESIGN.md 9절). */
  compact?: boolean
}

export function ChangeBand({ comparison, result, onRestore, onDismiss, compact = false }: Props) {
  const rows = compareResults(comparison.before, result)
  if (rows.length === 0) return null
  return (
    <section aria-label="바뀐 점" className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 font-semibold">
          {comparison.label}
          <span className="font-normal text-foreground-secondary"> — {changeHeadline(rows)}</span>
        </p>
        <Button size="sm" variant="outline" className={compact ? 'h-11 px-3' : undefined} onClick={onRestore}>
          <Undo2 aria-hidden />
          되돌리기
        </Button>
        <Button
          size={compact ? 'icon-lg' : 'icon-sm'}
          variant="ghost"
          className={compact ? 'size-11' : undefined}
          aria-label="바뀐 점 닫기"
          onClick={onDismiss}
        >
          <X aria-hidden />
        </Button>
      </div>
      <ul className="mt-2 grid gap-x-6 gap-y-1 text-sm [grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr))]">
        {rows.map((row) => {
          const { tone, icon: Icon, spoken } = LOOK[row.direction]
          return (
            <li key={row.id} data-change={row.id} className="flex flex-wrap items-center gap-x-1.5">
              <Icon aria-hidden className={`size-3.5 shrink-0 ${tone}`} />
              <span className="sr-only">{spoken}:</span>
              <span className="text-foreground-secondary">{row.label}</span>
              <span className="tabular-nums">{row.before}</span>
              <ArrowRight aria-hidden className="size-3.5 text-foreground-secondary" />
              <span className="sr-only">에서</span>
              <span className={`font-semibold tabular-nums ${tone}`}>{row.after}</span>
              {row.delta && <span className={`tabular-nums ${tone}`}>({row.delta})</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
