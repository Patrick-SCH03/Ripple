// 일정 탭 '공정 흐름'(엔진 0.10.0): 늦어지는 블록마다 블록 공정(소조립 → … → PE → 탑재)의 늘어난 일수와, 그 뒤 이정표
// (구역 출구 → 진수 → 시운전 → 인도). 후행 의장·선체도장은 공정도 표시용이라 점선 칸으로만 둔다(뜻은 일정 탭 ⓘ 계산 기준 — lib/processFlow FLOW_BASIS).
// 값은 lib/processFlow(결과의 schedule 필드 그대로). 칸은 줄을 바꿔 좁은 화면에서도 가로로 넘치지 않는다.
import { ChevronRight, Flag } from 'lucide-react'
import type { AnalysisResult } from '@/api/client'
import { processFlow, stepDays } from '@/lib/processFlow'
import { cn } from '@/lib/utils'

interface Chip {
  key: string
  name: string
  days: number | null
  /** 이정표(깃발 아이콘) · 표시용(점선, 계산하지 않음). */
  kind?: 'milestone' | 'display'
  note?: string
}

function Chips({ chips, label }: { chips: Chip[]; label: string }) {
  return (
    <ol aria-label={label} className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-1.5">
      {chips.map((chip, i) => {
        const late = (chip.days ?? 0) > 0
        // 화살표는 li 안(ol의 직속 자식은 li만) — 앞 칸과의 사이 표시라 읽기에서는 숨긴다
        return (
          <li key={chip.key} className="inline-flex items-center gap-x-1">
            {i > 0 && <ChevronRight aria-hidden className="size-3.5 shrink-0 text-foreground-secondary" />}
            <span
              className={cn(
                'inline-flex h-7 items-center gap-1 rounded-sm border px-2 text-sm whitespace-nowrap tabular-nums',
                late ? 'border-danger/50 bg-danger/10 font-semibold text-danger' : 'border-border text-foreground-secondary',
                chip.kind === 'display' && 'border-dashed',
              )}
            >
              {chip.kind === 'milestone' && <Flag aria-hidden className="size-3.5" />}
              <span>{chip.name}</span>
              {chip.days !== null && late && <span className="font-bold">{stepDays(chip.days)}</span>}
              {chip.note && <span className="font-normal">{chip.note}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export function ProcessFlowView({ result }: { result: AnalysisResult }) {
  const flow = processFlow(result)
  const { exit, delivery } = flow.milestones
  const milestones: Chip[] = [
    {
      key: 'exit',
      name: exit.zone ? `${exit.zone} 출구` : '구역 출구',
      days: exit.days,
      kind: 'milestone',
      note: exit.days > 0 ? undefined : '그대로',
    },
    { key: 'display', name: '후행 의장·선체도장', days: null, kind: 'display', note: '표시용' },
    { key: 'launch', name: '진수', days: null, kind: 'milestone' },
    { key: 'sea_trial', name: '시운전', days: null, kind: 'milestone' },
    {
      key: 'delivery',
      name: '인도',
      days: delivery.days,
      kind: 'milestone',
      note: delivery.days === null ? '계산 불가' : delivery.days > 0 ? undefined : '그대로',
    },
  ]
  return (
    <section aria-labelledby="flow-title" data-testid="process-flow" className="space-y-2 border-t border-border pt-3">
      <h4 id="flow-title" className="text-md font-semibold">
        공정 흐름
      </h4>
      <div className="space-y-2">
        {flow.blocks.map((block) => (
          <div key={block.block} className="grid grid-cols-[3.75rem_minmax(0,1fr)] items-start gap-2">
            <span className="pt-1 font-mono text-sm font-medium">{block.block}</span>
            <Chips
              label={`${block.block} 블록 공정`}
              chips={block.steps.map((step) => ({ key: step.kind, name: step.name, days: step.days }))}
            />
          </div>
        ))}
        <div className="grid grid-cols-[3.75rem_minmax(0,1fr)] items-start gap-2">
          <span className="pt-1 text-sm text-foreground-secondary">이정표</span>
          <Chips label="이정표" chips={milestones} />
        </div>
      </div>

    </section>
  )
}
