// 검토서 앞 절: 변경 내용·사유 · 판정과 핵심 수치(표) · 영향 범위 요약 · 조치 사항(+ 확인 필요 항목).
import { VerdictBadge } from '@/components/common/VerdictBadge'
import type { ReportModel } from '@/lib/report'
import { Section } from './Section'
import type { SheetModel } from './sheet'

export function ChangeSection({ change, number }: { change: SheetModel['change']; number: number }) {
  return (
    <Section number={number} title="변경 내용·사유" testId="report-change">
      <table className="doc-table">
        <tbody>
          <tr>
            <th scope="row">변경 내용</th>
            <td>
              <ul className="space-y-0.5" data-testid="report-ops">
                {change.ops.map((op, i) => (
                  <li key={`${op}-${i}`}>{op}</li>
                ))}
              </ul>
            </td>
          </tr>
          <tr>
            <th scope="row">변경 원인</th>
            <td data-testid="report-cause">{change.cause}</td>
          </tr>
          {change.opinion && (
            <tr>
              <th scope="row">담당자 의견</th>
              <td data-testid="report-opinion">{change.opinion}</td>
            </tr>
          )}
          {change.rawText && (
            <tr>
              <th scope="row">요청 원문</th>
              <td className="whitespace-pre-line">{change.rawText}</td>
            </tr>
          )}
        </tbody>
      </table>
    </Section>
  )
}

export function VerdictSection({ model, sheet, number }: { model: ReportModel; sheet: SheetModel; number: number }) {
  return (
    <Section number={number} title="판정과 핵심 수치" testId="report-verdict">
      <div className="report-keep mb-2 flex flex-wrap items-start gap-3">
        <VerdictBadge level={model.verdict.level} />
        <ul className="min-w-0 flex-1 list-disc space-y-0.5 pl-5">
          {model.verdict.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
      <table className="doc-table figures-table" data-testid="report-numbers">
        <tbody>
          {sheet.figures.map((row) => (
            <tr key={row.label} data-key={row.label}>
              <th scope="row">{row.label}</th>
              {/* 값 조각(' · ')마다 한 덩어리 — '807 MH · ≈ 4,007만원'이 좁은 화면에서 조각 사이에서만 줄을 바꾼다 */}
              <td className="w-40 font-bold tabular-nums">
                {row.value.split(' · ').map((part, i) => (
                  <span key={part} className="whitespace-nowrap">
                    {i > 0 && ' · '}
                    {part}
                  </span>
                ))}
              </td>
              <td className="text-foreground-secondary">
                {row.detail}
                {row.caution && <span className="block font-semibold text-warning">{row.caution}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}

export function ScopeSection({ scope, number }: { scope: SheetModel['scope']; number: number }) {
  return (
    <Section number={number} title="영향 범위 요약" testId="report-scope">
      <table className="doc-table text-center">
        <thead>
          <tr>
            {scope.counts.map((c) => (
              <th key={c.label} scope="col">
                {c.label}
              </th>
            ))}
            <th scope="col">2차 영향</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          <tr>
            {scope.counts.map((c) => (
              <td key={c.label} className="font-semibold">
                {c.count}
              </td>
            ))}
            <td className="font-semibold">{scope.secondary}</td>
          </tr>
        </tbody>
      </table>
      {scope.highlights.length > 0 && (
        <p className="report-keep mt-1.5" data-testid="report-secondary">
          <span className="font-semibold">주요 2차 영향: </span>
          {scope.highlights.join(' · ')}
        </p>
      )}
    </Section>
  )
}

export function TodoSection({ model, number }: { model: ReportModel; number: number }) {
  return (
    <Section number={number} title="조치 사항" testId="report-todos">
      {model.todos.length === 0 ? (
        <p>조치 항목 없음</p>
      ) : (
        <ol className="list-decimal space-y-1 pl-5">
          {model.todos.map((todo) => (
            <li key={todo.title} className="report-keep">
              <span className="font-semibold">{todo.title}</span>
              <span> — {todo.detail}</span>
              {todo.note && <span className="block text-foreground-secondary">{todo.note}</span>}
            </li>
          ))}
        </ol>
      )}
      <p className="mt-2 font-semibold">확인 필요 항목</p>
      {model.checklist.length === 0 ? (
        <p data-testid="report-checklist">없음</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-5" data-testid="report-checklist">
          {model.checklist.map((item) => (
            <li key={`${item.source}-${item.text}`} className="report-keep">
              <span className="text-foreground-secondary">{item.source} · </span>
              {item.text}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
