// 엑셀 가져오기 품질 리포트(DESIGN.md 6절): 성공·실패 상자 → 오류 → 확인할 것(시트·행·열 위치, 앞에서부터 몇 줄만).
// 상태 올리기는 지금 지도에 적용하면 바뀌는 것과 반영할 수 없는 항목을 함께 보인다.
import type { ApiError, ImportPreview, StatusImportPreview } from '@/api/client'
import { formatDay } from '@/lib/format'
import { countsText, head, reportOf, type IssueLine } from '@/lib/importReport'
import { diffLines } from '@/lib/mapDiff'
import { cn } from '@/lib/utils'

const SHOWN_ERRORS = 50
const SHOWN_WARNINGS = 30

/** active: 이 파일로 만든 지도가 이미 지금 쓰는 지도(같은 파일을 다시 올렸거나, 연결이 끊겼지만 전환은 됐음). */
export function ReportView({ preview, failure, active }: { preview: ImportPreview; failure: ApiError | null; active: boolean }) {
  const { summary, info } = preview
  const report = reportOf(summary)
  const ok = info !== null && info !== undefined
  return (
    <div className="space-y-3" data-testid="import-report">
      {ok ? (
        <div className="rounded-md border border-success/40 bg-success/8 px-3 py-2">
          <p className="font-semibold">지도 만들기 가능</p>
          <p className="mt-0.5 text-foreground-secondary">
            {summary.file} · {countsText(info)}
            {info.status_date && ` · 자료 기준일 ${formatDay(info.status_date)}`}
          </p>
        </div>
      ) : (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/8 px-3 py-2">
          <p className="font-semibold">지도 만들기 실패 — 오류 {report.errors.length}건</p>
          <p className="mt-0.5 text-foreground-secondary">
            열 확인으로 돌아가 고르기 또는 원본 엑셀의 아래 위치를 고친 뒤 다시 올리기
          </p>
        </div>
      )}
      {active ? (
        <p role="status" data-testid="import-active" className="font-medium">
          지금 쓰는 지도
        </p>
      ) : (
        failure && (
          <p role="alert" className="text-danger">
            {failure.message}
          </p>
        )
      )}
      {report.errors.length > 0 && <IssueList title="오류" lines={report.errors} limit={SHOWN_ERRORS} tone="danger" />}
      {report.warnings.length > 0 && (
        <IssueList title="확인할 것" lines={report.warnings} limit={SHOWN_WARNINGS} tone="warning" />
      )}
    </div>
  )
}

/** 상태 올리기 결과: 읽기 품질 + 지금 지도에 적용하면 바뀌는 것(단계·납기·실적) · 반영할 수 없는 항목. */
export function StatusReportView({ result, failure }: { result: StatusImportPreview; failure: ApiError | null }) {
  const report = reportOf(result.summary)
  const preview = result.preview
  const changes = preview ? diffLines(preview.diff) : []
  const ready = !!result.import_id
  return (
    <div className="space-y-3" data-testid="status-report">
      {ready ? (
        <div className="rounded-md border border-success/40 bg-success/8 px-3 py-2">
          <p className="font-semibold">지금 지도에 반영 가능 — 바뀌는 것 {changes.length}건</p>
          <p className="mt-0.5 text-foreground-secondary">
            {result.summary.file}
            {preview && preview.diff.confirmed_only > 0 && ` · 값은 그대로이고 확인만 남는 것 ${preview.diff.confirmed_only}건`}
          </p>
        </div>
      ) : (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/8 px-3 py-2">
          <p className="font-semibold">
            반영 불가 — {report.errors.length > 0 ? `읽기 오류 ${report.errors.length}건` : `맞지 않는 항목 ${preview?.problems.length ?? 0}건`}
          </p>
          <p className="mt-0.5 text-foreground-secondary">
            하나라도 맞지 않으면 전부 그대로 · 원본 엑셀의 아래 위치를 고친 뒤 다시 올리기
          </p>
        </div>
      )}
      {failure && (
        <p role="alert" className="text-danger">
          {failure.message}
          {failure.problems.length > 0 && `: ${failure.problems.join(' / ')}`}
        </p>
      )}
      {preview && preview.problems.length > 0 && (
        <IssueList
          title="맞지 않는 항목"
          lines={preview.problems.map((p) => ({
            where: p.source?.sheet ? `${p.source.sheet} ${p.source.row ?? ''}행 · ${p.entity_id}` : p.entity_id,
            message: p.message,
          }))}
          limit={SHOWN_ERRORS}
          tone="danger"
        />
      )}
      {changes.length > 0 && (
        <section aria-label="바뀌는 것">
          <h3 className="mb-1 text-sm font-semibold">바뀌는 것 {changes.length}건</h3>
          <ul className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2 text-sm">
            {changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}
      {report.errors.length > 0 && <IssueList title="오류" lines={report.errors} limit={SHOWN_ERRORS} tone="danger" />}
      {report.warnings.length > 0 && (
        <IssueList title="확인할 것" lines={report.warnings} limit={SHOWN_WARNINGS} tone="warning" />
      )}
    </div>
  )
}

function IssueList({
  title,
  lines,
  limit,
  tone,
}: {
  title: string
  lines: IssueLine[]
  limit: number
  tone: 'danger' | 'warning'
}) {
  const { shown, rest } = head(lines, limit)
  return (
    <section aria-label={title}>
      <h3 className={cn('mb-1 text-sm font-semibold', tone === 'danger' ? 'text-danger' : 'text-warning')}>
        {title} {lines.length}건
      </h3>
      <ul className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2 text-sm">
        {shown.map((line, i) => (
          <li key={i}>
            <span className="font-medium">{line.where}</span>
            <span className="text-foreground-secondary"> — {line.message}</span>
          </li>
        ))}
        {rest > 0 && <li className="text-foreground-secondary">그 밖에 {rest}건</li>}
      </ul>
    </section>
  )
}
