// 결재 띠 아래 안내 줄: 가정 계산 · 흐름 안내(기록된 분석 열기 · 저장된 리포트 열기) · 흐린 단추의 이유.
interface Props {
  /** 가정 계산 이름(보류 적용 등) — 기록하면 그 가정이 개정에 함께 남는다. */
  assumed: string | null
  notice: string | null
  /** 기록된 분석을 지금 지도에서 다시 열 수 있는 기록 ID. */
  recordedId: string | null
  onOpenRecorded?: (recordId: string) => void
  /** 계산 판이 바뀐 개정의 저장된 리포트 주소. */
  storedReport: string | null
  blocked: { labels: string; reason: string }[]
}

export function ApprovalNotes({ assumed, notice, recordedId, onOpenRecorded, storedReport, blocked }: Props) {
  return (
    <ul className="mt-1.5 space-y-0.5 text-sm" data-testid="approval-notes">
      {assumed && (
        <li className="text-foreground-secondary" data-testid="approval-assumed">
          지금 화면: 가정 계산({assumed}) · 기록 시 이 가정도 개정에 남음
        </li>
      )}
      {notice && (
        <li className="text-warning">
          {notice}
          {recordedId !== null && onOpenRecorded && (
            <>
              {' '}
              <button
                type="button"
                className="font-semibold text-primary underline-offset-2 hover:underline"
                onClick={() => onOpenRecorded(recordedId)}
                data-testid="open-recorded"
              >
                기록된 분석 열기
              </button>
            </>
          )}
          {storedReport !== null && (
            <>
              {' '}
              <a
                href={storedReport}
                target="_blank"
                rel="noopener"
                className="font-semibold text-primary underline-offset-2 hover:underline"
                data-testid="open-stored-report"
              >
                검토서 열기
              </a>
            </>
          )}
        </li>
      )}
      {blocked.map(({ labels, reason }) => (
        <li key={reason} className="text-foreground-secondary">
          {labels}: {reason}
        </li>
      ))}
    </ul>
  )
}
