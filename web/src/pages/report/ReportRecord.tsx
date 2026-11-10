// 검토서 뒤 절: 결재란(담당 · 파트장 · 팀장 · 본부장 — 기록된 결재만, 없으면 빈칸) · 붙임의 결재 이력.
import { StateChip } from '@/components/records/StateChip'
import type { ReportModel } from '@/lib/report'
import { Section } from './Section'
import type { SheetModel } from './sheet'

export function SignSection({ sheet, number }: { sheet: SheetModel; number: number }) {
  return (
    <Section number={number} title="결재" testId="report-signs">
      <table className="doc-table sign-table text-center" aria-label="결재란">
        <thead>
          <tr>
            {sheet.signs.map((cell) => (
              <th key={cell.role} scope="col" className="w-1/4">
                {cell.role}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="sign-row">
            {sheet.signs.map((cell) => (
              <td key={cell.role} data-role={cell.role} data-testid="report-sign">
                {cell.name && (
                  <>
                    <span className="block font-semibold">{cell.name}</span>
                    <span className="block text-xs">
                      {cell.mark}
                      {cell.proxy && ' · 전결'}
                    </span>
                  </>
                )}
              </td>
            ))}
          </tr>
          <tr>
            {sheet.signs.map((cell) => (
              <td key={cell.role} className="h-7 text-xs tabular-nums">
                {cell.day}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="mt-1 text-xs text-foreground-secondary">
        {sheet.line ? `결재선 ${sheet.line} · ` : ''}기록된 검토 요청·결정만 표시(서명 아님) · 빈칸 = 기록 없음
      </p>
    </Section>
  )
}

export function HistorySection({ history }: { history: ReportModel['history'] }) {
  return (
    <Section className="report-annex-section" title="결재 이력" testId="report-history">
      <ol className="space-y-1.5">
        {history.map((entry) => (
          <li key={entry.seq} className="report-keep">
            <div className="flex flex-wrap items-center gap-2">
              <StateChip state={entry.state} />
              <span className="font-medium">{entry.label}</span>
              <span className="text-foreground-secondary">
                {entry.who} · {entry.when}
              </span>
            </div>
            {entry.notes.length > 0 && (
              <ul className="mt-0.5 pl-1 text-foreground-secondary">
                {entry.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </Section>
  )
}
