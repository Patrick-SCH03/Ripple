// 일정 탭: 늦어질 수 있는 구역 출구 · 공정 흐름(블록 공정 → 이정표, 엔진 0.10.0 PE·시운전) · 인도. 없으면 한 줄로
// 알린다(DESIGN.md 2절).
// 줄 고르기·순서는 lib/schedule.ts(판단 리포트와 같게). 자재가 늦게 오면(일정 위험)은 대표 일정 옆 칸과 아래 줄로 따로 싣는다.
// 수치는 CPM 추정이라 '예상'으로 부르고 전제(SCHEDULE_BASIS)·위험 뜻·공정 흐름 칸의 뜻은 맨 위 'ⓘ 계산 기준' 하나에 둔다.
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { formatDay } from '@/lib/format'
import { zoneName } from '@/lib/labels'
import { FLOW_BASIS, processFlow } from '@/lib/processFlow'
import {
  type ExitMarginRow,
  SCHEDULE_BASIS,
  marginText,
  riskBasisText,
  riskDeliveryText,
  scheduleQuiet,
  scheduleSummary,
} from '@/lib/schedule'
import { ProcessFlowView } from './ProcessFlow'

/** 늦어지지 않았지만 여유가 줄어든 구역 출구(명세 6-7): 판정에는 안 쓰는 정보라 회색 글로. */
function Margins({ margins }: { margins: ExitMarginRow[] }) {
  if (margins.length === 0) return null
  return (
    <section aria-labelledby="margin-title" data-testid="schedule-margins" className="border-t border-border pt-3">
      <h4 id="margin-title" className="mb-1.5 text-md font-semibold">
        늦어지지 않지만 여유가 줄어든 구역 출구
      </h4>
      <ul className="space-y-0.5 text-sm tabular-nums text-foreground-secondary">
        {margins.map((margin) => (
          <li key={margin.exit_activity_id}>{marginText(margin)}</li>
        ))}
      </ul>
    </section>
  )
}

/**
 * 일정 계산 기준(추정의 전제 · 자재가 늦게 오면의 뜻 · 공정 흐름 칸의 뜻): 탭 아래 회색 두세 줄 대신 맨 위 'ⓘ 계산 기준' 하나에.
 * 뜻은 그대로이고(리포트는 문서라 그대로 싣는다) 화면에서는 한 단계 아래로 내린다(DESIGN.md 2절).
 */
function Basis({ risk }: { risk: string | null }) {
  return (
    <div className="flex justify-end" data-testid="schedule-basis">
      <InfoPop
        title="일정 계산 기준"
        label="계산 기준"
        lines={[SCHEDULE_BASIS, ...(risk ? [risk] : []), FLOW_BASIS]}
      />
    </div>
  )
}

export function ScheduleView({ result }: { result: AnalysisResult }) {
  const summary = scheduleSummary(result)
  const { exits, activities, delivery, deliveryUnknown, risk, margins } = summary

  if (scheduleQuiet(summary)) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium">일정 지연 없음</p>
          <Basis risk={null} />
        </div>
        <Margins margins={margins} />
      </div>
    )
  }
  const riskColumn = risk?.exitsLater ?? false
  // 블록 공정 꼴로 읽은 공정은 공정 흐름에, 읽지 못한 공정(가져온 지도의 다른 ID 꼴)만 표로
  const flowIds = new Set(processFlow(result).others.map((other) => other.id))
  const others = activities.filter((activity) => flowIds.has(activity.id))
  return (
    <div className="space-y-4">
      <Basis risk={risk ? riskBasisText(risk) : null} />
      {exits.length > 0 && (
        <section aria-labelledby="exit-title">
          <h4 id="exit-title" className="mb-2 text-md font-semibold">
            늦어질 수 있는 구역 출구
          </h4>
          <table className="w-full text-sm" data-testid="schedule-exits">
            <thead className="text-left text-foreground-secondary">
              <tr className="border-b border-border">
                <th className="py-1.5 font-medium">구역</th>
                <th className="py-1.5 font-medium">기준 일정</th>
                <th className="py-1.5 font-medium">변경 뒤</th>
                <th className="py-1.5 text-right font-medium">예상 지연</th>
                {riskColumn && <th className="py-1.5 pl-3 text-right font-medium">자재가 늦게 오면</th>}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {exits.map((exit) => (
                <tr key={exit.exit_activity_id} className="border-b border-border">
                  <td className="py-2 font-medium">{zoneName(exit)}</td>
                  <td className="py-1.5">{formatDay(exit.base_date)}</td>
                  <td className="py-1.5">{exit.delay_days > 0 ? formatDay(exit.new_date) : '그대로'}</td>
                  <td className={`py-1.5 text-right font-medium ${exit.delay_days > 0 ? 'text-danger' : ''}`}>
                    {exit.delay_days > 0 ? `+${exit.delay_days}일` : '0일'}
                  </td>
                  {riskColumn && (
                    <td
                      className={`py-1.5 pl-3 text-right ${exit.risk && exit.risk.delay_days > exit.delay_days ? 'font-medium text-warning' : 'text-foreground-secondary'}`}
                    >
                      {exit.risk ? `+${exit.risk.delay_days}일` : ''}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <Margins margins={margins} />
      <ProcessFlowView result={result} />
      {others.length > 0 && (
        <section aria-labelledby="activity-title" className="border-t border-border pt-3">
          <h4 id="activity-title" className="mb-2 text-md font-semibold">
            그 밖에 늦어질 수 있는 공정
          </h4>
          <table className="w-full text-sm">
            <thead className="text-left text-foreground-secondary">
              <tr className="border-b border-border">
                <th className="py-1.5 font-medium">공정</th>
                <th className="py-1.5 text-right font-medium">늘어난 기간</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {others.map(({ id, name, days }) => (
                <tr key={id} className="border-b border-border">
                  <td className="py-1.5">{name}</td>
                  <td className="py-1.5 text-right font-medium">+{days}일</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {(delivery || risk?.delivery || (risk?.deliveryUnknown.length ?? 0) > 0) && (
        <section aria-labelledby="delivery-title" className="border-t border-border pt-3">
          <h4 id="delivery-title" className="mb-2 text-md font-semibold">
            인도
          </h4>
          {delivery && (
            <p className="tabular-nums">
              예상 인도 지연 {delivery.before}일 → {delivery.after}일
              {delivery.added > 0 && <span className="font-medium text-danger">(이 변경으로 +{delivery.added}일)</span>}
            </p>
          )}
          {risk?.delivery && (
            <p className="tabular-nums text-warning" data-testid="risk-delivery">
              {riskDeliveryText(risk.delivery)}
            </p>
          )}
          {risk && risk.deliveryUnknown.length > 0 && (
            <p className="text-warning" data-testid="risk-delivery-unknown">
              자재가 늦게 오면 인도 지연 계산 불가: {risk.deliveryUnknown.join(' ')}
            </p>
          )}
        </section>
      )}
      {deliveryUnknown.length > 0 && (
        <p className="text-sm text-foreground-secondary">인도 지연 계산 불가: {deliveryUnknown.join(' ')}</p>
      )}
    </div>
  )
}
