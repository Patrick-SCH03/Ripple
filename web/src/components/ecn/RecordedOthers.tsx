// 샘플에 없는 기록된 설계변경(비서 요청·다른 지도의 기록 — DESIGN.md 13절): 최신 개정 요약(판정·마감일·총액)과 결재 상태.
// 누르면 그 기록의 요청을 지금 지도에서 다시 분석한다(기록 당시 숫자는 이력 탭).
import type { EcnListItem } from '@/api/client'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { StateText } from '@/components/records/StateChip'
import { deadlineMark, isClosed } from '@/lib/ecnList'
import { MY_NEXT } from '@/lib/records'
import { EcnRow } from './EcnRow'

interface Props {
  items: EcnListItem[]
  chosen: string | null
  onOpen: (item: EcnListItem) => void
  /** 지금 지도 ID(기록의 지도가 다르면 '다른 지도 기록'). */
  snapshotId: string | null
  /** 내가 최신 개정을 기록한 건('내 건' 표시). */
  mineOf?: (ecnId: string) => boolean
  /** 내 건의 반려·보류 사유 한 줄(없으면 undefined). */
  reasonOf?: (ecnId: string) => string | undefined
}

export function RecordedOthers({
  items,
  chosen,
  onOpen,
  snapshotId,
  mineOf = () => false,
  reasonOf = () => undefined,
}: Props) {
  if (items.length === 0) return null
  return (
    <section aria-label="기록된 다른 설계변경" className="border-t border-border" data-testid="recorded-others">
      <h3 className="px-4 pt-3 pb-1 text-sm font-semibold text-foreground-secondary">
        다른 기록 <span className="tabular-nums">{items.length}</span>
      </h3>
      <ul className="divide-y divide-border">
        {items.map((item) => {
          const { status, latest } = item
          const mine = mineOf(status.ecn_id)
          const reason = reasonOf(status.ecn_id)
          return (
            <EcnRow
              key={status.ecn_id}
              title={status.title}
              mark={isClosed(status.state) ? null : deadlineMark(latest.deadline, latest.as_of)}
              tag={<VerdictBadge level={latest.verdict} size="sm" />}
              meta={
                <>
                  <StateText state={status.state} />
                  {' · '}
                  {mine && '내 건 · '}
                  <span className="font-mono">{status.ecn_id}</span>
                  {status.snapshot_id !== snapshotId && ' · 다른 지도'}
                </>
              }
              hint={[
                status.title,
                `${status.ecn_id} · 개정 ${status.revision}`,
                status.snapshot_id !== snapshotId && '다른 지도 기록',
                mine && MY_NEXT[status.state],
                reason,
              ]
                .filter(Boolean)
                .join(' · ')}
              extra={reason}
              total={latest.total.value}
              totalTitle="마지막 기록의 총변경비용"
              current={status.ecn_id === chosen}
              onClick={() => onOpen(item)}
              marks={{ 'data-ecn-item': true, 'data-recorded': true }}
            />
          )
        })}
      </ul>
    </section>
  )
}
