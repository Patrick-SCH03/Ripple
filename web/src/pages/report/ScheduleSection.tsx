// 리포트 '일정' 절: 늦어지지 않으면 한 줄(+ 여유가 줄어든 구역 출구), 늦어지면 구역 출구 표 → 여유 → 공정 → 인도 →
// 자재가 늦게 오면(위험) → 계산 기준.
import { formatDay } from '@/lib/format'
import { zoneName } from '@/lib/labels'
import type { ReportModel } from '@/lib/report'
import { SCHEDULE_BASIS, marginText, riskBasisText, riskDeliveryText, scheduleQuiet } from '@/lib/schedule'
import { Section } from './Section'

export function ScheduleSection({ schedule, number }: { schedule: ReportModel['schedule']; number?: number }) {
  return (
    <Section number={number} title="일정" testId="report-schedule">
      {scheduleQuiet(schedule) ? (
        <>
          <p>일정 지연 없음</p>
          {schedule.margins.length > 0 && (
            <p className="text-foreground-secondary" data-testid="report-margins">
              여유가 줄어든 구역 출구: {schedule.margins.map(marginText).join(' · ')}
            </p>
          )}
        </>
      ) : (
        <div className="space-y-2">
          {schedule.exits.length > 0 && <ExitTable schedule={schedule} />}
          {schedule.margins.length > 0 && (
            <p className="text-foreground-secondary" data-testid="report-margins">
              여유가 줄어든 구역 출구: {schedule.margins.map(marginText).join(' · ')}
            </p>
          )}
          {schedule.activities.length > 0 && (
            <p>
              늦어질 수 있는 공정: {schedule.activities.map((a) => `${a.name} +${a.days}일`).join(' · ')}
            </p>
          )}
          {schedule.delivery && (
            <p>
              예상 인도 지연 {schedule.delivery.before}일 → {schedule.delivery.after}일
              {schedule.delivery.added > 0 && `(이 변경으로 +${schedule.delivery.added}일)`}
            </p>
          )}
          {schedule.deliveryUnknown.length > 0 && (
            <p className="text-foreground-secondary">인도 지연 계산 불가: {schedule.deliveryUnknown.join(' ')}</p>
          )}
          {schedule.risk?.delivery && <p>{riskDeliveryText(schedule.risk.delivery)}</p>}
          {schedule.risk && schedule.risk.deliveryUnknown.length > 0 && (
            <p>자재가 늦게 오면 인도 지연 계산 불가: {schedule.risk.deliveryUnknown.join(' ')}</p>
          )}
          {schedule.risk && <p className="text-foreground-secondary">{riskBasisText(schedule.risk)}</p>}
          <p className="text-foreground-secondary" data-testid="report-schedule-basis">
            {SCHEDULE_BASIS}
          </p>
        </div>
      )}
    </Section>
  )
}

/** 늦어질 수 있는 구역 출구 표(위험이 대표보다 늦는 출구가 있으면 '자재가 늦게 오면' 칸). */
function ExitTable({ schedule }: { schedule: ReportModel['schedule'] }) {
  return (
    <table data-testid="report-exits">
      <thead>
        <tr className="border-b border-border text-left text-foreground-secondary">
          <th className="py-1 font-medium">늦어질 수 있는 구역 출구</th>
          <th className="py-1 font-medium">기준 일정</th>
          <th className="py-1 font-medium">변경 뒤</th>
          <th className="py-1 text-right font-medium">예상 지연</th>
          {schedule.risk?.exitsLater && <th className="py-1 pl-3 text-right font-medium">자재가 늦게 오면</th>}
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {schedule.exits.map((exit) => (
          <tr key={exit.exit_activity_id} className="border-b border-border">
            <td className="py-1">{zoneName(exit)}</td>
            <td className="py-1">{formatDay(exit.base_date)}</td>
            <td className="py-1">{exit.delay_days > 0 ? formatDay(exit.new_date) : '그대로'}</td>
            <td className="py-1 text-right">{exit.delay_days > 0 ? `+${exit.delay_days}일` : '0일'}</td>
            {schedule.risk?.exitsLater && (
              <td className="py-1 pl-3 text-right">{exit.risk ? `+${exit.risk.delay_days}일` : ''}</td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
