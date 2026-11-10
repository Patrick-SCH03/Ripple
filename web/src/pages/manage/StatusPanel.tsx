// 현황(관리자): 지금 쌓인 일 — 결재 대기와 마감 임박, 아직 결정 안 된 금액, 실행 중, 상태별 건수, 블록별로 몰린 곳.
import type { ManageOverview } from '@/api/client'
import { URGENT_DAYS, blockLabel, stateBars } from '@/lib/manage'
import { formatMoney } from '@/lib/money'
import { Stat } from './Stat'

export function StatusPanel({ data }: { data: ManageOverview }) {
  const { kpis } = data
  const days = data.performance.days
  return (
    <section aria-label="현황" className="space-y-6" data-testid="status-panel">
      {/* 숫자 카드 = 이름 + 큰 숫자, 보조 줄은 행동이 바뀌는 것 한 줄까지(DESIGN.md 6절): 기한 임박·지남만 남긴다 */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="결재 대기"
          value={`${kpis.waiting}건`}
          detail={kpis.urgent > 0 ? `기한 ${URGENT_DAYS}일 이내·지남 ${kpis.urgent}건` : undefined}
          tone={kpis.urgent > 0 ? 'danger' : 'neutral'}
        />
        <Stat label="미결정 설계변경" value={`${kpis.undecided}건`} />
        <Stat label="실행 중" value={`${kpis.in_progress}건`} />
        <Stat label={days === null ? '전체 기간 새 기록' : `최근 ${days}일 새 기록`} value={`${kpis.recorded_recent}건`} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-md font-semibold">상태별 설계변경</h3>
          <ul className="mt-3 space-y-2">
            {stateBars(data.states).map((bar) => (
              <li key={bar.state} className="grid grid-cols-[3.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 text-sm">
                <span className="text-foreground-secondary">{bar.label}</span>
                <span className="h-2.5 rounded-full bg-muted" aria-hidden>
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round(bar.ratio * 100)}%` }} />
                </span>
                <span className="text-right tabular-nums">{bar.count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="text-md font-semibold">설계변경 집중 블록</h3>
          {data.blocks.length === 0 ? (
            <p className="mt-3 text-sm text-foreground-secondary">진행 중인 설계변경 없음</p>
          ) : (
            <table className="mt-3 w-full text-sm">
              <thead className="text-left text-foreground-secondary">
                <tr className="border-b border-border">
                  <th className="py-1.5 font-medium">블록</th>
                  <th className="py-1.5 text-right font-medium">진행 중</th>
                  <th className="py-1.5 text-right font-medium">총변경비용 합</th>
                </tr>
              </thead>
              <tbody>
                {data.blocks.map((block) => (
                  <tr key={block.block_id} className="border-b border-border last:border-0">
                    <td className="py-1.5 font-mono">{blockLabel(block.block_id)}</td>
                    <td className="py-1.5 text-right tabular-nums">{block.open}건</td>
                    <td className="py-1.5 text-right tabular-nums">{formatMoney(block.total_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  )
}
