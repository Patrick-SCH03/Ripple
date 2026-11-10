// 성과(관리자): 기간 안 업무 결정 — 처리 속도, 마감 안 결재와 그로써 피한 추가손실, 더 저렴한 대안이 있던 승인, 담당자별 업무량.
// 개발 모드 결정은 서버가 빼고 보낸다. 정의는 펼침 안에 둔다(첫 화면은 숫자와 한 줄 설명만).
import type { ManageOverview } from '@/api/client'
import { Button } from '@/components/ui/button'
import { whoLabel } from '@/lib/account'
import { PERIODS, errorText, hoursText, percent, stepHoursText } from '@/lib/manage'
import { formatMoney, formatRange } from '@/lib/money'
import { Stat } from './Stat'
import { WideTable } from './WideTable'

interface Props {
  data: ManageOverview
  days: number | null
  onDays?: (days: number | null) => void
  /** 고른 기간을 읽는 중(그동안 숫자는 이전 기간 것이라 흐리게). */
  loading?: boolean
}

export function PerformancePanel({ data, days, onDays, loading = false }: Props) {
  const perf = data.performance
  const stale = loading && (perf.days ?? null) !== days
  return (
    <section aria-label="성과" aria-busy={stale} className="space-y-6" data-testid="performance-panel">
      {onDays && (
        <div role="group" aria-label="기간" className="flex flex-wrap items-center gap-2 print:hidden">
          {PERIODS.map((period) => (
            <Button
              key={period.label}
              size="sm"
              variant={days === period.days ? 'default' : 'outline'}
              aria-pressed={days === period.days}
              onClick={() => onDays(period.days)}
            >
              {period.label}
            </Button>
          ))}
          {stale && <span className="text-sm text-foreground-secondary">불러오는 중…</span>}
        </div>
      )}
      <div className={stale ? 'space-y-6 opacity-50 transition-opacity' : 'space-y-6'}>
        {perf.decided === 0 && (
          <p className="rounded-md border border-border px-4 py-3 text-sm text-foreground-secondary">
            이 기간 결정 없음 · 기간을 넓혀 확인
          </p>
        )}
        {/* 숫자 카드 = 이름 + 큰 숫자(DESIGN.md 6절): 큰 숫자를 되풀이하는 줄('n건 합계'·'없음')은 두지 않고, 항목 나열·단계별
            중앙값은 이름 옆 ⓘ로 */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Stat
            label="결정"
            value={`${perf.decided}건`}
            more={[`승인 ${perf.approved} · 반려 ${perf.rejected} · 보류 ${perf.held} · 담당자 처리 ${perf.settled ?? 0}`]}
          />
          <Stat label="반려율" value={percent(perf.reject_rate)} />
          <Stat
            label="결재 처리 시간(중앙값)"
            value={hoursText(perf.request_to_decision_hours)}
            more={[
              ...(stepHoursText(perf.steps) ? [`단계별 ${stepHoursText(perf.steps)}`] : []),
              `기록 → 검토 요청 ${hoursText(perf.record_to_request_hours)}`,
            ]}
          />
          <Stat
            label="기한 안 결재"
            value={percent(perf.on_time_rate)}
            more={[`승인 ${perf.approved}건 중 ${perf.on_time}건이 결정 기한 안`]}
            tone={perf.on_time_rate != null && perf.on_time_rate >= 0.9 ? 'success' : 'neutral'}
          />
          <Stat
            label="기한 안 결재로 피한 추가손실"
            value={formatMoney(perf.protected)}
            tone={perf.protected > 0 ? 'success' : 'neutral'}
          />
          <Stat
            label="더 저렴한 대안이 있던 승인"
            value={`${perf.cheaper_cases}건`}
            more={perf.cheaper_cases > 0 ? [`요청안과 차액 합 ${formatMoney(perf.cheaper_total)}`] : undefined}
          />
        </div>
        <div>
          <h3 className="text-md font-semibold">담당자별 업무량</h3>
          {perf.people.length === 0 ? (
            <p className="mt-3 text-sm text-foreground-secondary">이 기간 기록·검토 요청 없음</p>
          ) : (
            // 머리글이 짧아 휴대폰 폭에도 대개 들어간다(넘치면 가로 스크롤 안내)
            <WideTable label="담당자별 업무량 표">
              <table className="w-full text-sm">
                <thead className="text-left text-foreground-secondary">
                  <tr className="border-b border-border">
                    <th className="py-1.5 font-medium whitespace-nowrap">담당자</th>
                    <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">기록</th>
                    <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">검토 요청</th>
                    <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">반려 건</th>
                    <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">진행 중</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.people.map((person) => (
                    <tr key={person.actor.login_id} className="border-b border-border last:border-0">
                      <td className="py-1.5">{whoLabel(person.actor)}</td>
                      <td className="py-1.5 text-right tabular-nums">{person.recorded}</td>
                      <td className="py-1.5 text-right tabular-nums">{person.requested}</td>
                      <td className="py-1.5 text-right tabular-nums">{person.rejected}</td>
                      <td className="py-1.5 text-right tabular-nums">{person.open}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </WideTable>
          )}
        </div>
        <OutcomeTable data={data} />
        <details className="rounded-md border border-border bg-surface px-4 py-3 text-sm print:hidden">
          <summary className="cursor-pointer font-medium">지표 계산 방법</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-foreground-secondary">
            <li>
              결정: 기간 안 업무 결정(마지막 단계 승인 · 어느 단계든 반려·보류)만 집계 · 중간 단계 승인은 단계별 처리
              시간에만 · 담당자 처리(도면 개정뿐 · 승인 가능 — 결재선 없음)와 개발 모드 결정은 제외
            </li>
            <li>기한 안 결재: 승인일 ≤ 그 개정 분석의 결정 기한(실제 데이터는 실제 승인일, 합성 지도는 분석 기준일 + 기록 뒤 지난 날수)</li>
            <li>피한 추가손실: 결정 기한 안 승인 건마다 '결정 기한 다음 날 확정 시 늘었을 금액'(대표값)의 합 · 탐색 기간 안 손실 없던 건 제외</li>
            <li>더 저렴한 대안: 강도 사전검사를 충족한 대안의 최적 조합이 요청안보다 저렴한 승인(대안 선택 권고 아님 · 확인 대상)</li>
            <li>처리 시간: 단계마다 그 단계 시작부터, 중앙값 · 반려 건: 그 사람이 요청한 검토의 반려 수</li>
            <li>
              예측 대비 실적: 실행한 설계변경의 실제 비용 ↔ 승인 개정의 총변경비용(대표값) · 기간 무관 전부, 고친 건 마지막
              값
            </li>
          </ul>
        </details>
      </div>
    </section>
  )
}

/** 예측 대비 실적: 실행한 설계변경에 담당자가 넣은 실제 비용 ↔ 승인한 개정의 예측. 쌓이면 비용 가정을 고칠 근거가 된다. */
function OutcomeTable({ data }: { data: ManageOverview }) {
  const summary = data.outcomes
  return (
    <div data-testid="outcome-table">
      <h3 className="text-md font-semibold">예측 대비 실적</h3>
      <p className="mt-1 text-sm text-foreground-secondary">
        {summary.count === 0
          ? '실적 없음 · 실행한 설계변경에 실제 비용을 넣으면 표시'
          : `${summary.count}건 · 오차 중앙값 ${summary.median_abs_error == null ? '—' : `±${percent(summary.median_abs_error)}`} · 예측 범위 안 ${percent(summary.in_range_rate)}`}
      </p>
      {summary.rows.length > 0 && (
        <WideTable label="예측 대비 실적 표">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-foreground-secondary">
              <tr className="border-b border-border">
                <th className="py-1.5 font-medium whitespace-nowrap">설계변경</th>
                <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">예측(승인 개정)</th>
                <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">실적</th>
                <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">오차</th>
                <th className="py-1.5 pl-4 text-right font-medium whitespace-nowrap">출구 지연 예측 → 실적</th>
              </tr>
            </thead>
            <tbody>
              {summary.rows.map((row) => (
                <tr key={row.ecn_id} className="border-b border-border last:border-0">
                  <td className="py-1.5">
                    <span className="font-medium">{row.ecn_id}</span>{' '}
                    <span className="text-foreground-secondary">
                      {row.title} · 개정 {row.revision}
                    </span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums" title={formatRange(row.predicted.low, row.predicted.high)}>
                    {formatMoney(row.predicted.value)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{formatMoney(row.actual_krw)}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {errorText(row.error_rate)}
                    {!row.in_range && <span className="text-warning"> · 범위 밖</span>}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {row.predicted_delay_days}일 → {row.actual_delay_days == null ? '—' : `${row.actual_delay_days}일`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </WideTable>
      )}
    </div>
  )
}
