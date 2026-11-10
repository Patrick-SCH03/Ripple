// 결정을 기다리는 설계변경(관리자, 검토·보류 — DESIGN.md 13절): 추가손실 0 마감일이 급한 것부터. 누르면 그 개정의 기록된 분석을
// 연다(샘플의 기본 조건이 아니라 담당자가 기록한 조건 그대로 — 결재 띠에서 바로 결정할 수 있게).
import type { EcnListItem } from '@/api/client'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { StateText } from '@/components/records/StateChip'
import { whoLabel } from '@/lib/account'
import { deadlineMark } from '@/lib/ecnList'
import { pendingDecisions } from '@/lib/records'
import { EcnRow } from './EcnRow'

interface Props {
  items: EcnListItem[]
  chosen: string | null
  onOpen: (item: EcnListItem) => void
}

export function PendingDecisions({ items, chosen, onOpen }: Props) {
  const pending = pendingDecisions(items)
  if (pending.length === 0) return null
  return (
    <section
      aria-label="결재를 기다리는 설계변경"
      className="border-b border-border bg-[color-mix(in_oklab,var(--primary)_5%,var(--surface))]"
      data-testid="pending-decisions"
    >
      <h3 className="px-4 pt-3 pb-1 text-sm font-semibold text-primary">
        결재 대기 <span className="tabular-nums">{pending.length}</span>
      </h3>
      <ul className="divide-y divide-border">
        {pending.map((item) => {
          const { status, latest } = item
          return (
            <EcnRow
              key={status.ecn_id}
              title={status.title}
              mark={deadlineMark(latest.deadline, latest.as_of)}
              tag={<VerdictBadge level={latest.verdict} size="sm" />}
              meta={
                <>
                  <StateText state={status.state} />
                  {' · '}
                  <span className="font-mono">{status.ecn_id}</span>
                  {status.review && ` · ${status.review.requested_by.name}`}
                </>
              }
              hint={[
                status.title,
                `${status.ecn_id} · 개정 ${status.revision}`,
                status.review && `${whoLabel(status.review.requested_by)} 요청`,
              ]
                .filter(Boolean)
                .join(' · ')}
              total={latest.total.value}
              totalTitle="그 개정의 총변경비용"
              current={status.ecn_id === chosen}
              onClick={() => onOpen(item)}
              marks={{ 'data-pending-item': true }}
            />
          )
        })}
      </ul>
    </section>
  )
}
