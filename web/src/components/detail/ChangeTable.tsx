// 판단 요약 첫 소구역 '변경 내용'(DESIGN.md 6절): 부재 · 항목 · 변경 전 · 변경 후 · 도면 대조표. 값은 요청 연산과 분석 그래프
// 그대로(lib/changeTable). 처음 5행, 넘으면 '전체 n행'. 부재 이름을 누르면 영향 지도에서 그 카드를 골라 근거를 연다.
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { CHANGE_ROWS_SHOWN, changeTable } from '@/lib/changeTable'
import type { AnalysisResult } from '@/api/client'
import { cn } from '@/lib/utils'
import { SubSection } from './DetailSection'

interface Props {
  result: Pick<AnalysisResult, 'request' | 'graph' | 'trace'>
  /** 부재 이름 누름: 영향 지도에서 그 엔터티 근거 열기(비용 줄 '영향 지도에서 근거 보기'와 같은 길). */
  onEvidence: (entityId: string) => void
  /** 좁은 화면: 누르는 칸 44px. */
  compact?: boolean
}

export function ChangeTable({ result, onEvidence, compact = false }: Props) {
  const [open, setOpen] = useState(false)
  const view = changeTable(result)
  if (view.rows.length === 0) return null
  const over = view.rows.length > CHANGE_ROWS_SHOWN
  const rows = open || !over ? view.rows : view.rows.slice(0, CHANGE_ROWS_SHOWN)
  return (
    <SubSection
      id="change-table-title"
      title="변경 내용"
      first
      testId="change-table"
      info={<span className="text-sm text-foreground-secondary">{view.rows.length}행</span>}
    >
      <div className="@container overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="text-left text-foreground-secondary">
            <tr className="border-b border-border-strong">
              <th scope="col" className="py-1.5 pr-2 font-medium">
                부재
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                항목
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-medium">
                변경 전
              </th>
              <th scope="col" className="px-2 py-1.5 text-right font-medium">
                변경 후
              </th>
              {view.hasDrawing && (
                <th scope="col" className="py-1.5 pl-2 font-medium">
                  도면
                </th>
              )}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-border align-top" data-key={row.key}>
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  {row.selectable && row.entityId ? (
                    <button
                      type="button"
                      className={cn('rounded-sm text-left whitespace-nowrap text-primary underline-offset-4 hover:underline', compact && 'min-h-11')}
                      title={row.code ?? undefined}
                      onClick={() => onEvidence(row.entityId as string)}
                      aria-label={`${row.part} · 영향 지도에서 근거 보기`}
                    >
                      {row.part}
                    </button>
                  ) : (
                    <span className="whitespace-nowrap" title={row.code ?? undefined}>{row.part}</span>
                  )}
                  {/* 부재 번호는 폭이 넉넉할 때만 이름 옆에(좁으면 이름만 한 줄 — 번호는 마우스 올림) */}
                  {row.code && (
                    <span className="ml-1.5 hidden font-mono text-xs text-foreground-secondary @2xl:inline">{row.code}</span>
                  )}
                </th>
                <td className="px-2 py-1.5 whitespace-nowrap">{row.item}</td>
                <td className="px-2 py-1.5 text-right whitespace-nowrap">{row.before}</td>
                <td className="px-2 py-1.5 text-right font-semibold whitespace-nowrap">{row.after}</td>
                {view.hasDrawing && (
                  <td className="py-1.5 pl-2">
                    {/* 번호만 고정폭(한글 '개정'은 고정폭 글꼴에서 벌어져 보임). 좁으면 번호 | 개정 사이에서만 줄바꿈 —
                        구분은 '·' 대신 간격이라 접혀도 둘째 줄이 '· 개정 A'처럼 점으로 시작하지 않는다 */}
                    {row.drawing ? (
                      <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
                        <span className="font-mono whitespace-nowrap">{row.drawing.no}</span>
                        {row.drawing.revision && (
                          <span className="whitespace-nowrap text-foreground-secondary">개정 {row.drawing.revision}</span>
                        )}
                        {row.drawing.more > 0 && <span className="whitespace-nowrap">외 {row.drawing.more}</span>}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {over && (
        <Button variant="ghost" size="sm" className={cn('mt-1', compact && 'h-11')} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? '접기' : `전체 ${view.rows.length}행`}
        </Button>
      )}
    </SubSection>
  )
}
