// 검토서의 표 절: 비용 내역(1.35.0 구분이 있으면 공수 · 재료비(자재 차이 · 구매) 묶음과 소계, 항목·금액·범위 + 합계) ·
// 붙임의 연결 추적 · 확정을 미루면 · 대안.
import { DELAY_RIPPLE_SCOPE } from '@/lib/delayRipple'
import { traceLinkText, type ReportModel } from '@/lib/report'
import { Section } from './Section'

export function CostSection({ model, number }: { model: ReportModel; number?: number }) {
  const hasSections = model.costs.some((cost) => cost.level === 'section')
  return (
    <Section number={number} title="비용 내역" testId="report-costs">
      <table className="doc-table doc-list cost-table">
        <thead>
          <tr className="border-b border-border text-left text-foreground-secondary">
            <th className="py-1 font-medium">항목</th>
            <th className="py-1 text-right font-medium">금액</th>
            <th className="py-1 text-right font-medium">범위</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {model.costs.map((cost, i) => (
            <tr
              key={`${cost.level}-${cost.label}-${i}`}
              data-cost-level={cost.level}
              className={
                cost.level === 'section'
                  ? 'doc-cost-section border-b border-border font-semibold'
                  : cost.level === 'part'
                    ? 'border-b border-border text-foreground-secondary'
                    : 'border-b border-border'
              }
            >
              <td className={cost.level === 'line' && hasSections ? 'py-1 pr-2 pl-3' : 'py-1 pr-2'}>
                {cost.label}
                {cost.meta &&
                  (cost.level === 'section' ? (
                    <span className="font-normal text-foreground-secondary"> · {cost.meta}</span>
                  ) : (
                    <span className="cost-meta text-foreground-secondary">{cost.meta}</span>
                  ))}
                {cost.unknown && <span className="text-warning"> (판단 불가)</span>}
              </td>
              <td className="py-1 text-right whitespace-nowrap">{cost.value}</td>
              <td className="py-1 text-right whitespace-nowrap text-foreground-secondary">{cost.range ?? ''}</td>
            </tr>
          ))}
          <tr className="doc-total font-semibold">
            <td className="py-1">{model.total.sum ? `합계(총변경비용 = ${model.total.sum})` : '합계'}</td>
            <td className="py-1 text-right whitespace-nowrap" data-testid="report-total">
              {model.total.value}
            </td>
            <td className="py-1 text-right whitespace-nowrap text-foreground-secondary">{model.total.range ?? ''}</td>
          </tr>
          {model.outside && (
            <tr className="border-t border-border" data-testid="report-outside">
              <td className="py-1 pr-2">
                총액 밖: 지연 파급 비용(가정)
                <span className="block text-xs text-foreground-secondary">
                  {model.outside.reason ?? model.outside.formula} · {DELAY_RIPPLE_SCOPE}
                </span>
              </td>
              <td className="py-1 text-right align-top whitespace-nowrap">{model.outside.value}</td>
              <td className="py-1 text-right align-top whitespace-nowrap text-foreground-secondary">
                {model.outside.range ?? ''}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Section>
  )
}

export function TraceSection({ trace }: { trace: NonNullable<ReportModel['trace']> }) {
  return (
    <Section className="report-annex-section" title="연결 추적(도면 → 블록 → 발주 → 공정)" testId="report-trace">
      <table>
        <thead>
          <tr className="border-b border-border text-left text-foreground-secondary">
            <th className="py-1 font-medium">대상 부재</th>
            <th className="py-1 font-medium">도면</th>
            <th className="py-1 font-medium">블록</th>
            <th className="py-1 font-medium">발주 품목</th>
            <th className="py-1 font-medium">공정</th>
          </tr>
        </thead>
        <tbody>
          {trace.map((chain) => (
            <tr key={chain.part_id} className="border-b border-border align-top">
              <td className="py-1">
                {chain.label}
                {chain.gaps.length > 0 && <span className="block text-xs">끊김: {chain.gaps.join(' · ')}</span>}
              </td>
              <td className="py-1">{chain.drawing?.label ?? '—'}</td>
              <td className="py-1">{chain.block ? traceLinkText(chain.block) : '—'}</td>
              <td className="py-1">{chain.po_lines.map(traceLinkText).join(', ') || '—'}</td>
              <td className="py-1">{chain.activities.map(traceLinkText).join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}

export function StepsSection({ steps }: { steps: ReportModel['steps'] }) {
  return (
    <Section className="report-annex-section" title="확정을 미루면" testId="report-steps">
      {steps.length === 0 ? (
        <p>탐색 기간 안 확정을 미뤄도 금액 그대로</p>
      ) : (
        <table>
          <thead>
            <tr className="border-b border-border text-left text-foreground-secondary">
              <th className="py-1 font-medium">이날 확정하면</th>
              <th className="py-1 text-right font-medium">총변경비용</th>
              <th className="py-1 text-right font-medium">추가손실</th>
              <th className="py-1 pl-3 font-medium">바뀌는 내용</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {steps.map((step) => (
              <tr key={step.day} className="border-b border-border">
                {/* 날짜·금액은 한 덩어리 — 설명 칸이 길면 '4억 / 2,736 / 만원'처럼 쪼개지던 것 */}
                <td className="py-1 whitespace-nowrap">{step.day}</td>
                <td className="py-1 pl-2 text-right whitespace-nowrap">{step.total}</td>
                <td className="py-1 pl-2 text-right whitespace-nowrap">{step.added}</td>
                <td className="py-1 pl-3 text-foreground-secondary">{step.events}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  )
}

export function AlternativesSection({ alternatives }: { alternatives: NonNullable<ReportModel['alternatives']> }) {
  return (
    <Section className="report-annex-section" title="대안" testId="report-alternatives">
      {alternatives.headline && (
        <p className="report-keep mb-2">
          <span className="font-semibold">권고: {alternatives.headline.title}</span> —{' '}
          {alternatives.headline.detail}
        </p>
      )}
      <table>
        <thead>
          <tr className="border-b border-border text-left text-foreground-secondary">
            <th className="py-1 font-medium">대안</th>
            <th className="py-1 font-medium">판정(예비)</th>
            <th className="py-1 text-right font-medium">출구 예상 지연</th>
            <th className="py-1 text-right font-medium">결정 기한</th>
            <th className="py-1 text-right font-medium">총변경비용</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {alternatives.rows.map((row) => (
            <tr key={row.name} className="border-b border-border">
              <td className="py-1">
                {row.name}
                {row.recommended && <span className="font-semibold"> · 권고</span>}
              </td>
              <td className="py-1">{row.judgement}</td>
              <td className="py-1 text-right">{row.exit}</td>
              <td className="py-1 text-right">{row.deadline}</td>
              <td className="py-1 text-right">{row.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  )
}
