// 블록별 강재 중량 변화(계약 1.34.0, docs/engine.md(비용·일정) 12절): 블록 · 원래 · 새 · 차이(t) · 부재 수 표와 합계,
// 중량 정보 없는 부재 수, 무게중심 안내. 숫자는 결과 weight_change 그대로(lib/weightChange.ts가 포맷·정렬만).
// 상세 화면과 검토서(pages/report)가 같은 부품을 쓴다 — 배치는 부르는 쪽이 정한다(제목은 heading으로 선택).
import { InfoPop } from '@/components/common/InfoPop'
import { cn } from '@/lib/utils'
import { COG_NOTE, WEIGHT_BASIS, partsText, weightView, type WeightChangeData } from '@/lib/weightChange'

export interface WeightChangeProps {
  /** 분석 결과의 weight_change. 이 판 전 기록(필드 없음)이면 undefined·null → 안내 한 줄. */
  weight: WeightChangeData | null | undefined
  /** 표 위 제목(없으면 제목 없이 — 부르는 쪽 절 제목을 쓸 때). */
  heading?: string
  /** 상세(업무 화면): 중량 근거·무게중심 안내를 제목 옆 ⓘ로 내린다(검토서는 문서라 표 아래에 그대로). */
  compactNotes?: boolean
  className?: string
}

export function WeightChange({ weight, heading, compactNotes = false, className }: WeightChangeProps) {
  const view = weightView(weight)
  return (
    <section
      className={cn('weight-change text-sm', className)}
      aria-label={heading ? undefined : '중량 변화'}
      aria-labelledby={heading ? 'weight-change-title' : undefined}
      data-testid="weight-change"
    >
      {heading && (
        <div className="mb-2 flex items-center gap-1.5">
          <h4 id="weight-change-title" className="text-md font-semibold">
            {heading}
          </h4>
          {compactNotes && (
            <InfoPop
              title="중량 근거"
              lines={[...(view && !view.empty ? [WEIGHT_BASIS] : []), COG_NOTE]}
            />
          )}
        </div>
      )}
      {view === null ? (
        <p className="text-foreground-secondary" data-testid="weight-change-old">
          중량 변화 · 이 판 전 기록(계산 안 함)
        </p>
      ) : view.empty ? (
        <p data-testid="weight-change-empty">중량이 바뀌는 부재 없음</p>
      ) : (
        <table className="w-full border-collapse" data-testid="weight-change-table">
          <thead className="text-left text-foreground-secondary">
            <tr className="border-b border-border-strong">
              <th scope="col" className="py-1.5 pr-2 font-medium">
                블록
              </th>
              <th scope="col" className="py-1.5 pl-2 text-right font-medium">
                원래(t)
              </th>
              <th scope="col" className="py-1.5 pl-2 text-right font-medium">
                새(t)
              </th>
              <th scope="col" className="py-1.5 pl-2 text-right font-medium">
                차이(t)
              </th>
              <th scope="col" className="py-1.5 pl-2 text-right font-medium">
                부재 수
              </th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {view.rows.map((row) => (
              <tr key={row.key} className="border-b border-border align-top" data-key={row.key}>
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  {row.code && <span className="font-mono">{row.code}</span>}
                  {row.code && row.name && ' '}
                  {row.name && <span className="text-foreground-secondary">{row.name}</span>}
                </th>
                <td className="py-1.5 pl-2 text-right whitespace-nowrap">{row.before}</td>
                <td className="py-1.5 pl-2 text-right whitespace-nowrap">{row.after}</td>
                <td className="py-1.5 pl-2 text-right font-semibold whitespace-nowrap">{row.delta}</td>
                <td className="py-1.5 pl-2 text-right whitespace-nowrap">{partsText(row)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular-nums">
            <tr className={cn('weight-change-total border-t-2 border-border-strong bg-muted font-semibold', compactNotes && 'text-base')}>
              <th scope="row" className="py-1.5 pr-2 text-left">
                합계
              </th>
              <td className="py-1.5 pl-2 text-right whitespace-nowrap">{view.total.before}</td>
              <td className="py-1.5 pl-2 text-right whitespace-nowrap">{view.total.after}</td>
              <td className="py-1.5 pl-2 text-right whitespace-nowrap" data-testid="weight-change-total">
                {view.total.delta}
              </td>
              <td className="py-1.5 pl-2 text-right whitespace-nowrap">{partsText(view.total)}</td>
            </tr>
          </tfoot>
        </table>
      )}
      {compactNotes ? (
        view?.missingNote && <p className="mt-1.5 text-sm text-warning">{view.missingNote}</p>
      ) : (
        <ul className="mt-1.5 space-y-0.5 text-xs text-foreground-secondary">
          {view?.missingNote && <li className="text-warning">{view.missingNote}</li>}
          {view && !view.empty && <li>중량 근거: {WEIGHT_BASIS}</li>}
          <li data-testid="weight-change-cog">{COG_NOTE}</li>
        </ul>
      )}
    </section>
  )
}
