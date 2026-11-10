// 결재 띠 가운데: 결재선 단계 칩(검토 중) · 개정 · 기록한 사람 · 시각 · 검토 요청한 사람 · 검토서 인쇄 링크(작은 한 줄) ·
// 담당자 의견 인용(기록이 없으면 다음 단계 안내).
import type { AuditEntry, EcnStatus, Me, RevisionSummary } from '@/api/client'
import { can, formatKstTime, whoLabel } from '@/lib/account'
import { signsOf } from '@/lib/approval'
import { reportPath } from '@/lib/report'
import { cn } from '@/lib/utils'
import { LineProgress } from '../LineProgress'

export function ApprovalMeta({
  me,
  status,
  latest,
  audit,
}: {
  me: Me
  status: EcnStatus | null
  latest: RevisionSummary | null
  /** 그 설계변경의 감사 줄(결재선 앞 단계 승인을 찾는다). */
  audit: readonly AuditEntry[]
}) {
  const review = status?.review
  // 담당자 의견: 진행 중 검토를 연 감사 줄(검토 요청)의 사유 — 결재자가 결재 띠에서 바로 본다
  const opinion = review ? audit.find((entry) => entry.seq === review.seq)?.detail.reason : null
  // 반려·보류 사유: 목록 줄에서 뺀 한 줄을 여기(고른 건의 결재 띠)에 — 고쳐서 다시 올릴 것을 바로 찾게
  const decided = status?.state === 'rejected' || status?.state === 'on_hold'
  const decision = decided
    ? [...audit].reverse().find((entry) => entry.action === 'reject' || entry.action === 'hold')?.detail.reason
    : null
  return (
    // 글이 24em(글자 크기 기준)보다 좁아지면 단추가 아래 줄로 내려간다 — 1024·768px에서 결재선·기록 줄이 단추 옆 좁은 칸에서
    // 너덧 줄로 눌리지 않게. 위에서부터: 결재선 단계 칩(검토 중) · 기록 메타 작은 한 줄 · 반려·보류 사유 · 담당자 의견 인용
    <div className="min-w-0 flex-1 basis-[24em]" data-testid="approval-meta">
      {latest ? (
        <>
          {review && (
            <LineProgress variant="step" steps={review.steps} current={review.step} signed={signsOf(audit, review.seq)} />
          )}
          <p className={cn('text-sm text-foreground-secondary', review && 'mt-1.5')}>
            개정 {latest.revision} · {whoLabel(latest.recorded_by)} 기록 · {formatKstTime(latest.recorded_at)}
            {review && <> · 검토 요청 {whoLabel(review.requested_by)}</>}
            {status && (
              <>
                {' · '}
                <a
                  href={reportPath(status.ecn_id, latest.revision)}
                  target="_blank"
                  rel="noopener"
                  className="font-medium text-primary underline-offset-2 hover:underline"
                  data-testid="open-report"
                >
                  검토서 인쇄
                </a>
              </>
            )}
          </p>
          {decision && (
            <p className="mt-1 text-base text-foreground" data-testid="decision-reason">
              {status?.state === 'rejected' ? '반려' : '보류'} 사유 · {decision}
            </p>
          )}
          {opinion && (
            <figure
              className="mt-2 rounded-sm border-l-4 border-border-strong bg-muted px-3 py-2"
              data-testid="review-opinion"
            >
              <figcaption className="text-sm font-medium text-foreground-secondary">담당자 의견</figcaption>
              <blockquote className="mt-0.5 text-base text-foreground break-keep">“{opinion}”</blockquote>
            </figure>
          )}
        </>
      ) : (
        <p className="text-sm text-foreground-secondary">
          {can(me, 'record') ? '기록 없음 · 판단이 끝나면 검토 요청' : '기록 없음 · 담당자가 검토를 요청하면 결재 가능'}
        </p>
      )}
    </div>
  )
}