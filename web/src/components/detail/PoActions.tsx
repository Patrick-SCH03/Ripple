// 비용 탭 맨 위 '발주 조치'(docs/engine.md(비용·일정) 4-10): 발주 품목마다 확정일 단계와 해야 할 조치·금액.
// 금액·근거는 아래 비용 표의 같은 줄과 같다(새 계산 없음). 발주와 무관한 변경이면 그리지 않는다.
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { formatMoney } from '@/lib/money'
import { poActions } from '@/lib/poActions'

export function PoActions({ result }: { result: AnalysisResult }) {
  const rows = poActions(result)
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="po-actions-title" className="mb-5 text-sm" data-testid="po-actions">
      <div className="mb-2 flex items-center gap-1.5">
        <h4 id="po-actions-title" className="text-md font-semibold">
          발주 조치
        </h4>
        {/* 대체 범위 안내는 표 아래 회색 줄 대신 ⓘ */}
        <InfoPop
          title="발주 조치"
          lines={['대체는 같은 규격 재고·잉여 자재 전용만', '다른 규격 대체품·취소·재주문 실행 상태는 제외']}
        />
      </div>
      <table className="w-full">
        <thead className="text-left text-foreground-secondary">
          <tr className="border-b border-border">
            <th className="py-1.5 font-medium">품목</th>
            <th className="py-1.5 font-medium">확정일 단계</th>
            <th className="py-1.5 font-medium">조치</th>
            <th className="py-1.5 text-right font-medium">금액</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.lineId} className="border-b border-border align-top">
              <td className="py-1.5 tabular-nums">{row.lineId}</td>
              <td className="py-1.5">{row.stage ?? '—'}</td>
              <td className="py-1.5">
                <ul className="space-y-0.5">
                  {row.actions.map((action, i) => (
                    <li key={`${action.kind}-${i}`}>{action.text}</li>
                  ))}
                </ul>
              </td>
              <td className="py-1.5 text-right tabular-nums">{formatMoney(row.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
