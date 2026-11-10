// 이력 탭(근거 탭 옆, DESIGN.md 13절): 감사 줄을 시간순으로 — 누가·언제·무엇을, 개정이면 그 개정의 판정·총액·조건.
// 숫자는 기록 본문에서 만든 개정 요약(RevisionSummary) 그대로다(지금 다시 계산한 값이 아님).
import type { EcnDetail, RevisionSummary } from '@/api/client'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { formatKstTime, whoLabel } from '@/lib/account'
import { deadlineMark } from '@/lib/ecnList'
import { formatDay } from '@/lib/format'
import { formatMoney } from '@/lib/money'
import { ENTRY_LABEL, entryNotes } from '@/lib/records'
import { reportPath } from '@/lib/report'
import { StateChip } from './StateChip'

/** waiting: 아래 결과와 고른 설계변경이 아직 다름(새 분석·이력을 기다리는 중) — '기록 없음'으로 오해하지 않게. */
export function HistoryTab({ detail, waiting = false }: { detail: EcnDetail | null; waiting?: boolean }) {
  if (waiting) {
    return (
      <p className="py-4 text-sm text-foreground-secondary" data-testid="history-waiting">
        이력 불러오는 중…
      </p>
    )
  }
  if (!detail) {
    return (
      <p className="py-4 text-sm text-foreground-secondary" data-testid="history-empty">
        기록 없음 · 결재 띠의 '검토 요청'·'기록만 남기기'로 개정 1부터 기록
      </p>
    )
  }
  const revisions = new Map(detail.revisions.map((r) => [r.revision, r]))
  const entries = [...detail.audit].reverse()
  return (
    <ol className="space-y-3" aria-label="결재 이력" data-testid="history">
      {entries.map((entry) => {
        const revision = entry.action === 'record' && entry.revision ? revisions.get(entry.revision) : undefined
        const notes = entryNotes(entry)
        return (
          <li key={entry.seq} className="rounded-md border border-border px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <StateChip state={entry.detail.to_state} />
              <span className="font-semibold">
                {ENTRY_LABEL[entry.action]}
                {entry.revision ? ` · 개정 ${entry.revision}` : ''}
              </span>
              <span className="text-foreground-secondary">
                {whoLabel(entry.actor)} · {formatKstTime(entry.at)}
              </span>
              {revision && (
                <a
                  href={reportPath(detail.status.ecn_id, revision.revision)}
                  target="_blank"
                  rel="noopener"
                  className="ml-auto font-medium text-primary underline-offset-2 hover:underline"
                  data-testid="history-report"
                >
                  검토서
                </a>
              )}
            </div>
            {revision && <RevisionLine revision={revision} />}
            {notes.length > 0 && (
              <ul className="mt-1.5 space-y-0.5 text-sm text-foreground-secondary">
                {notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function RevisionLine({ revision }: { revision: RevisionSummary }) {
  const mark = deadlineMark(revision.deadline, revision.as_of)
  const parts = [
    `총변경비용 ${formatMoney(revision.total.value)}`,
    `결정 기한 ${mark.text}`,
    `확정일 ${formatDay(revision.confirm_on)}`,
    revision.holds.length > 0 ? `발주 보류 ${revision.holds.length}건` : null,
    revision.alternatives ? '대안 포함' : null,
    revision.checklist > 0 ? `확인 필요 ${revision.checklist}개` : null,
  ].filter(Boolean)
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      <VerdictBadge level={revision.verdict} size="sm" />
      <span className="tabular-nums">{parts.join(' · ')}</span>
    </div>
  )
}
