// ECN 상세(가운데 칸, DESIGN.md 2절 정보 위계): 이전 결과 알림 → 머리(제목·확정일·판정과 이유·요약 복사) → 결재 띠 →
// 구역 이동 막대(고정) → 구역 카드 넷: 판단 요약(변경 내용 전 → 후 · (검토 요청 전) 권고 대안 · 핵심 수치) → 영향 범위(영향 지도 · 연결 추적) →
// 할 일(조치 · 현장 상태 확인 · 사전 점검) → 근거 상세(비용 · 일정 · 추가손실 곡선 · 대안 · 이력 탭).
// 영향 지도는 서비스의 핵심 그림이라 탭에 숨기지 않고 판단 요약 바로 아래 구역에 둔다.
// 결과는 POST /api/analyses의 분석 결과이고, 결재 띠·이력은 그 ECN의 기록(docs/records.md)이다.
import { api, type AnalysisResult, type Me, type StatusUpdate } from '@/api/client'
import { ExcelExportButton } from '@/components/common/ExcelExportButton'
import { TermInfo } from '@/components/common/TermInfo'
import { ApprovalBand } from '@/components/records/ApprovalBand'
import { lineGuide, shownPlan, submitLine } from '@/lib/approval'
import { conditionLock } from '@/lib/records'
import { DETAIL_SECTION_IDS, detailNavItems, hasActions } from '@/lib/detailNav'
import { DETAIL_TABS_ID } from '@/lib/domIds'
import { precheckView } from '@/lib/precheck'
import { todos } from '@/lib/summary'
import type { AnalysisSession } from '@/state/useAnalysisSession'
import type { RecordsState } from '@/state/useRecords'
import { ActionsSection } from './ActionsSection'
import { BriefingCopy } from './BriefingCopy'
import { ChangeBand } from './ChangeBand'
import { ChangeTable } from './ChangeTable'
import { DeliveryBand } from './DeliveryBand'
import { DetailHeader } from './DetailHeader'
import { DetailNav } from './DetailNav'
import { DetailSection } from './DetailSection'
import { EvidenceTabs, type DetailTab } from './EvidenceTabs'
import { KeyNumbers } from './KeyNumbers'
import { PrecheckSection } from './PrecheckSection'
import { RecommendationBand } from './RecommendationBand'
import { ResultNotice } from './ResultNotice'
import { RipplePanel } from './RipplePanel'
import { TracePanel } from './TracePanel'
import { WeightChange } from './WeightChange'

export type { DetailTab } from './EvidenceTabs'

interface Props {
  session: AnalysisSession
  /** 좁은 화면: 영향 지도는 들여쓴 목록, 단추·탭은 터치 높이. */
  compact: boolean
  /** 근거 탭(비용·일정·곡선·대안·이력): 좁은 화면에서는 상세가 새로 마운트되므로 상태를 바깥(Workbench)이 든다. */
  tab: DetailTab
  onTab: (tab: DetailTab) => void
  /** 바깥에서 '이 엔터티의 근거 열기'를 요청할 때마다 늘어나는 번호(같은 엔터티를 다시 골라도 근거 제목으로 초점). */
  evidenceRequest: number
  /** 비용 줄·연결 추적의 '영향 지도에서 근거 보기': 엔터티를 골라 영향 지도의 근거를 연다(App이 초점을 든다). */
  onEvidence: (entityId: string) => void
  /** 결과가 없을 때 안내(설계변경 목록이 없는 지도는 비서로 시작). */
  emptyText?: string
  /** 결재(기록·승인): 고른 ECN의 상태·개정·감사와 행동. */
  records: RecordsState
  me: Me
  /** 지금 작업 공간의 지도 ID(최신 기록의 지도와 대조). */
  snapshotId: string | null
  /** 로그인 모드(개발 모드면 자기 결정·개발 승인 실행이 됨). */
  loginMode: boolean
  /** 결재 띠의 '기록된 분석 열기': 그 기록의 요청을 지금 지도에서 다시 분석한다. */
  onOpenRecorded?: (recordId: string) => void
  /** 오늘(KST). 현장 상태 확인은 오늘 날짜로만 남긴다. */
  today: string
  /** 현장 상태를 확인·수정할 수 있는가(기록 권한). */
  canConfirm: boolean
  /** 상태 확인·수정을 보낸다(지도가 바뀌면 같은 요청으로 다시 분석). 실패면 이유 문장. */
  onStatusUpdate: (update: StatusUpdate) => Promise<string | null>
  /** 1.37.0 사전 점검 '통보문 보기'의 메일 카드를 Gmail로 열 수 있는가(합성 데이터 지도만). */
  webMail?: boolean
}

/** 영향 범위 카드 아래 중량 변화: 두께·강종 변경은 야드 중량 관리 항목. 바뀐 강재가 있을 때만(0이면 숨김, DESIGN.md 2절). */
function ImpactWeight({ result }: { result: AnalysisResult }) {
  if ((result.weight_change?.blocks.length ?? 0) === 0) return null
  // 소구역 모양(위 구분선 + 소제목)은 다른 소구역과 같게, 중량 근거·무게중심 안내는 제목 옆 ⓘ로
  return <WeightChange weight={result.weight_change} heading="중량 변화" compactNotes className="border-t border-border pt-3" />
}

export function EcnDetail({
  session,
  compact,
  tab,
  onTab,
  evidenceRequest,
  onEvidence,
  emptyText,
  records,
  me,
  snapshotId,
  loginMode,
  onOpenRecorded,
  today,
  canConfirm,
  onStatusUpdate,
  webMail = false,
}: Props) {
  const { result, selected, select, changeHold, changeOnboard } = session
  // 결재선 계획(서버 값): 화면의 분석 = 고른 설계변경의 최신 개정일 때만(기록 전·다른 분석이면 그리지 않음)
  // 결재 계획(서버 한 곳 규칙): 검토 중이면 상세의 남은 단계(화면 = 그 개정일 때만), 그 밖은 분석 응답에 실린 값 —
  // 기록 전 분석에서도 결재 올릴 기한·결재선 안내가 보인다. 결정이 끝난 건(승인·실행·종료)에는 그리지 않는다
  const matched = records.detailReady && records.ecnId === result?.request.change.ecn_id
  const state = matched ? records.detail?.status.state : undefined
  const reviewing = state === 'in_review' || state === 'on_hold'
  const decided = state === 'approved' || state === 'in_progress' || state === 'closed'
  const plan = reviewing ? shownPlan(records.detail, result) : (result?.approval_plan ?? null)
  const before = !reviewing && !decided // 결재선 안내는 검토 요청 전(기록 전·분석·반려)에만
  // 결재 중·결정된 건은 기록한 담당자만 조건을 바꾼다(결재자가 다른 분석을 보지 않게 — lib/records conditionLock)
  const lock = matched ? conditionLock(records.detail, me) : null
  // 할 일 구역: 조치 묶음(조치·현장 상태·결재 안내)이나 사전 점검 중 하나라도 있으면 그린다
  const approvalGuide = before ? lineGuide(plan) : null
  const actionsShown = result ? hasActions(result, approvalGuide) : false
  const prechecksShown = result ? precheckView(result) !== null : false
  const todoCount = result ? todos(result).length : 0
  // 마감일 카드의 작은 곡선·권고 대안 띠의 '대안 비교': 그 탭을 열고 탭 줄까지 내려 그 탭에 초점(움직임 줄이기면 바로)
  const openTab = (next: DetailTab) => {
    onTab(next)
    requestAnimationFrame(() => {
      const list = document.getElementById(DETAIL_TABS_ID)
      const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      list?.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' })
      list?.querySelector<HTMLElement>('[role="tab"][data-state="active"]')?.focus({ preventScroll: true })
    })
  }
  return (
    <>
      <ResultNotice session={session} />
      <div data-detail-scroll className="min-h-0 flex-1 overflow-y-auto">
        <DetailHeader
          key={session.draftContext.ecnId ?? ''}
          shown={session.shownContext ?? session.draftContext}
          draft={session.draftContext}
          editable={session.draftValid && lock === null}
          lockNote={lock}
          verdict={result?.verdict ?? null}
          actions={
            result && (
              <div className="flex flex-wrap items-center justify-end gap-2">
                <BriefingCopy result={result} compact={compact} />
                {/* 보던 분석의 요청 그대로 → 엑셀(서버가 같은 요청을 다시 분석해 같은 숫자로 씀) */}
                <ExcelExportButton
                  load={() => api.exportAnalysis(result.request)}
                  fallbackName={`Ripple_분석_${result.request.change.ecn_id ?? 'ECN'}.xlsx`}
                  compact={compact}
                  testId="analysis-export"
                />
              </div>
            )
          }
          onConfirmOn={session.setConfirmOn}
          onDesignStatus={session.setDesignStatus}
          onEffectiveOn={session.setEffectiveOn}
          onCause={session.setCause}
        />
        <ApprovalBand
          me={me}
          records={records}
          result={result}
          resultReady={session.state === 'current'}
          snapshotId={snapshotId}
          loginMode={loginMode}
          onOpenRecorded={onOpenRecorded}
          today={today}
        />
        {!result ? (
          <p className="p-6 text-sm text-foreground-secondary">
            {session.busy ? '계산 중…' : (emptyText ?? '목록에서 설계변경 선택 → 분석 결과')}
          </p>
        ) : (
          <>
            <DetailNav
              items={detailNavItems(result, actionsShown || prechecksShown)}
              compact={compact}
              resetKey={result.analysis_id}
            />
            <div className="space-y-3 bg-canvas px-3 pt-3 pb-6">
              <DetailSection id={DETAIL_SECTION_IDS.summary} title="판단 요약">
                {/* 무엇이 어떻게 바뀌나(부재 · 전 → 후 · 도면): 설계·생산 담당자가 숫자보다 먼저 확인 — 다른 건으로 옮기면 접힘으로 */}
                <ChangeTable
                  key={`change-${result.request.change.ecn_id ?? ''}`}
                  result={result}
                  onEvidence={onEvidence}
                  compact={compact}
                />
                {session.comparison && (
                  <ChangeBand
                    comparison={session.comparison}
                    result={result}
                    onRestore={session.restore}
                    onDismiss={session.dismissComparison}
                    compact={compact}
                  />
                )}
                <DeliveryBand result={result} />
                {/* 더 저렴한 대안: 검토 요청 전에만(결재 중에는 결정 도우미의 권고). 기록 상태를 읽기 전(다른 건을 고른 직후 등)에는
                    그리지 않는다 — 검토 중인 건에 잠깐 보이거나 앞 건의 결과로 대안 계산을 보내지 않게 */}
                {before && matched && (
                  <RecommendationBand
                    result={result}
                    compact={compact}
                    onOpen={(request, label) => session.open(request, label)}
                    onCompare={() => openTab('alternatives')}
                  />
                )}
                {/* 마감일 카드의 '확정일을 ○월 ○일로'는 머리 확정일 칸과 같은 길(초안 고치기 → 다시 분석) */}
                <KeyNumbers
                  result={result}
                  canEdit={session.draftValid && session.state === 'current' && lock === null}
                  compact={compact}
                  onConfirmOn={session.setConfirmOn}
                  onOpenCurve={() => openTab('curve')}
                  submit={decided ? null : submitLine(plan, reviewing)}
                />
              </DetailSection>
              <DetailSection id={DETAIL_SECTION_IDS.impact} title="영향 범위" aside={<TermInfo term="mapUse" />}>
                {/* 시연 대본이 이 이름으로 지도를 찾는다(lib/demoScenarios DEMO_SELECTORS.map) */}
                <div className="space-y-3" data-testid="impact-map">
                  <RipplePanel
                    view={result}
                    selected={selected}
                    onSelect={select}
                    compact={compact}
                    focusRequest={evidenceRequest}
                  />
                  <TracePanel result={result} onEvidence={onEvidence} />
                </div>
                <ImpactWeight result={result} />
              </DetailSection>
              {(actionsShown || prechecksShown) && (
                <DetailSection
                  id={DETAIL_SECTION_IDS.actions}
                  title="할 일"
                  aside={todoCount > 0 ? `조치 ${todoCount}` : undefined}
                >
                  <ActionsSection
                    // 다른 설계변경으로 옮기면 접힘 상태를 처음(접힘)으로
                    key={`actions-${result.request.change.ecn_id ?? ''}`}
                    result={result}
                    compact={compact}
                    canChange={session.state === 'current'}
                    onHold={(poId, days) => changeHold(result.analysis_id, poId, days)}
                    onOnboard={(on) => changeOnboard(result.analysis_id, on)}
                    today={today}
                    canConfirm={canConfirm && session.state === 'current'}
                    onStatusUpdate={onStatusUpdate}
                    approval={approvalGuide}
                  />
                  {prechecksShown && (
                    <PrecheckSection
                      key={`prechecks-${result.request.change.ecn_id ?? ''}`}
                      result={result}
                      compact={compact}
                      onEvidence={onEvidence}
                      first={!actionsShown}
                      webMail={webMail}
                    />
                  )}
                </DetailSection>
              )}
              <DetailSection id={DETAIL_SECTION_IDS.evidence} title="근거 상세">
                <EvidenceTabs
                  result={result}
                  session={session}
                  records={records}
                  compact={compact}
                  tab={tab}
                  onTab={onTab}
                  onEvidence={onEvidence}
                />
              </DetailSection>
            </div>
          </>
        )}
      </div>
    </>
  )
}
