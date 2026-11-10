// 검토서 문서 머리: 문서명 · 제목, 그 아래 칸 표(ECN 번호·개정 · 호선 · 대상 블록 · 작성일(KST) · 작성자 · 분석 조건 ·
// 설계 승인 · 발행) · 합성 데이터 표시 · 새 개정 안내.
import type { ReportModel } from '@/lib/report'
import { SHEET_TITLE, type SheetModel } from './sheet'

export function ReportHeader({ model, sheet, issuedAt }: { model: ReportModel; sheet: SheetModel; issuedAt: string }) {
  return (
    <header className="report-keep">
      <div className="flex items-end justify-between gap-4 border-b-4 border-double border-foreground pb-2">
        <div className="min-w-0">
          <h1 className="text-lg font-bold tracking-[0.2em]" data-testid="report-doc-name">
            {SHEET_TITLE}
          </h1>
          <p className="mt-1 text-base font-semibold" data-testid="report-title">
            {model.title}
          </p>
        </div>
        {model.synthetic && (
          <p className="shrink-0 rounded-sm border border-foreground px-2 py-0.5 text-xs font-semibold" data-testid="report-synthetic">
            합성 데이터
          </p>
        )}
      </div>
      <table className="doc-table facts-table mt-3" data-testid="report-facts">
        <tbody>
          <tr>
            <th scope="row">ECN 번호</th>
            <td>
              <span className="font-mono">{model.ecnId}</span> · 개정 {model.revision}
            </td>
            <th scope="row">호선</th>
            <td>{model.ships}</td>
          </tr>
          <tr>
            <th scope="row">대상 블록</th>
            <td className="font-mono" data-testid="report-blocks">
              {sheet.blocks}
            </td>
            <th scope="row">설계 승인</th>
            <td data-testid="report-design">{model.design}</td>
          </tr>
          <tr>
            <th scope="row">작성일</th>
            <td className="tabular-nums" data-testid="report-written">
              {sheet.writtenAt}
            </td>
            <th scope="row">작성자</th>
            <td>{model.recordedBy}</td>
          </tr>
          <tr>
            <th scope="row">분석 조건</th>
            <td colSpan={3}>{model.conditions.join(' · ')}</td>
          </tr>
          <tr>
            <th scope="row">발행</th>
            <td colSpan={3} className="tabular-nums">
              {issuedAt} · 기록 {model.recordId}
            </td>
          </tr>
        </tbody>
      </table>
      {model.newer !== null && (
        <p className="mt-2 border border-warning px-3 py-1.5 font-semibold text-warning" data-testid="report-newer">
          이 개정 뒤 새 개정 있음(최신 개정 {model.newer}) · 최신 판단은 그 개정의 검토서
        </p>
      )}
    </header>
  )
}
