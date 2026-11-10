// 설계변경 검토서 본문(DESIGN.md 14절, A4 세로): 문서 머리 → 1 변경 내용·사유 → 2 판정과 핵심 수치 → 3 영향 범위 요약 →
// 4 비용 내역 → 5 일정 → 6 중량 변화 → 7 조치 사항 → 8 결재 → 붙임(새 쪽: 확정을 미루면 · 대안 · 연결 추적 · 결재 이력) →
// 꼬리(출처 · 기록 · 쪽 번호는 @page 여백). 값은 모두 리포트 모델(lib/report.ts)·검토서 값(sheet.ts) 그대로이고, 여기서는
// 절을 차례대로 놓기만 한다. 실제 야드 양식이 아닌 일반 사내 검토서 구성이다.
import { WeightChange } from '@/components/detail/WeightChange'
import type { ReportModel } from '@/lib/report'
import { ReportHeader } from './ReportHeader'
import { HistorySection, SignSection } from './ReportRecord'
import { ChangeSection, ScopeSection, TodoSection, VerdictSection } from './ReportSummary'
import { AlternativesSection, CostSection, StepsSection, TraceSection } from './ReportTables'
import { ScheduleSection } from './ScheduleSection'
import { Section } from './Section'
import { pageCss, sourceLine, SHEET_TITLE, type SheetModel } from './sheet'

export function Report({ model, sheet, issuedAt }: { model: ReportModel; sheet: SheetModel; issuedAt: string }) {
  const source = sourceLine(model.synthetic)
  return (
    <>
      {/* 인쇄 쪽 머리·꼬리(쪽 번호) — 이 문서가 떠 있는 동안만 */}
      <style>{pageCss(`${SHEET_TITLE} · ${model.ecnId} 개정 ${model.revision}`, source)}</style>
      <ReportHeader model={model} sheet={sheet} issuedAt={issuedAt} />
      <ChangeSection number={1} change={sheet.change} />
      <VerdictSection number={2} model={model} sheet={sheet} />
      <ScopeSection number={3} scope={sheet.scope} />
      <CostSection number={4} model={model} />
      <ScheduleSection number={5} schedule={model.schedule} />
      <Section number={6} title="중량 변화" testId="report-weight">
        <WeightChange weight={sheet.weight} />
      </Section>
      <TodoSection number={7} model={model} />
      <SignSection number={8} sheet={sheet} />
      <div className="report-annex" data-testid="report-annex">
        <p className="report-annex-title mt-8 border-b-4 border-double border-foreground pb-1 text-base font-bold">
          붙임 · 근거
        </p>
        <StepsSection steps={model.steps} />
        {model.alternatives && <AlternativesSection alternatives={model.alternatives} />}
        {model.trace && model.trace.length > 0 && <TraceSection trace={model.trace} />}
        <HistorySection history={model.history} />
      </div>
      <footer className="report-foot mt-8 border-t border-foreground pt-2 text-xs" data-testid="report-foot">
        <p className="font-semibold">{source}</p>
        <p className="text-foreground-secondary">
          기록 {model.recordId}의 분석 그대로(지금 다시 계산한 값 아님) · 판정은 예비 판단, 확인 필요 항목은 담당자 별도 확인
        </p>
      </footer>
    </>
  )
}
