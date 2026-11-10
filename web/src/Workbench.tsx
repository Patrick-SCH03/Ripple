// 한 작업 공간(지도)의 업무 화면: 세션·비서·분석 기준을 모아 뼈대와 칸에 나눠 준다.
// App이 작업 공간 토큰을 key로 그려, 지도가 바뀌면(같은 지도를 다시 켜거나 서버가 다시 켜져도) 이 화면의 상태가 통째로
// 새로 만들어진다 — 이전 지도의 결과·초안·대화·진행 중 응답이 남지 않는다(docs/operations.md(서비스) 6절).
// 동작(연 차례·기록 열기·비서 칸·근거·상태 갱신·명령 팔레트)은 state/의 훅이 맡고, 여기서는 그것을 조립해 그린다.
import { useState, type Dispatch, type SetStateAction } from 'react'
import { AsideActions } from './components/assistant/AsideActions'
import { AssistantPanel } from './components/assistant/AssistantPanel'
import { DemoMenu } from './components/demo/DemoMenu'
import { EcnDetail, type DetailTab } from './components/detail/EcnDetail'
import { ListSortButton } from './components/ecn/EcnList'
import { ListPaneBody } from './components/ecn/ListPaneBody'
import { IntakeDialog } from './components/intake/IntakeDialog'
import { RequestEditor } from './components/input/RequestEditor'
import { AppShell, type PaneId } from './components/shell/AppShell'
import { CommandPalette } from './components/shell/CommandPalette'
import { NoticeBar } from './components/shell/NoticeBar'
import { TopBar } from './components/shell/TopBar'
import { can } from './lib/account'
import { ASSISTANT_INPUT_ID, ASSISTANT_TOGGLE_ID } from './lib/domIds'
import { useSignedIn } from './state/sessionContext'
import { todayKst } from './lib/basis'
import { listedCount, type ListView } from './lib/ecnList'
import { recordParam } from './lib/route'
import type { ThemeState } from './lib/theme'
import type { Notice } from './lib/workspace'
import { isCompact, type LayoutMode } from './lib/viewport'
import { turnActions } from './state/turnActions'
import { useAnalysisSession } from './state/useAnalysisSession'
import { useAssistant } from './state/useAssistant'
import { useAssistantDock } from './state/useAssistantDock'
import { useBasis } from './state/useBasis'
import { useCommandPalette } from './state/useCommandPalette'
import { useEvidence } from './state/useEvidence'
import { NoticeContext } from './state/noticeContext'
import { useNoticeBridge } from './state/useNoticeBridge'
import { useOpenOrder } from './state/useOpenOrder'
import { useRecordLinks } from './state/useRecordLinks'
import { useRecords } from './state/useRecords'
import { useStatusUpdate } from './state/useStatusUpdate'
import type { ImportMode } from '@/components/workspace/ImportDialog'
import type { WorkspaceState } from './state/useWorkspace'

const ASSISTANT_TITLE = 'AI 비서'
const RECORDS_FAILED: Notice = {
  tone: 'warning',
  text: '결재 상태 목록 불러오기 실패 · 결재 대기·내 건 칸과 결재 상태가 빠질 수 있음, 잠시 뒤 새로 고침',
}

/** 화면 배치: 작업 공간이 바뀌어도 유지한다(App이 가진다). */
export interface Layout {
  listOpen: boolean
  setListOpen: Dispatch<SetStateAction<boolean>>
  /** 1024~1439px: AI 비서 시트가 열렸나. */
  asideOpen: boolean
  setAsideOpen: Dispatch<SetStateAction<boolean>>
  /** 1440px 이상: AI 비서 칸을 펼쳐 두었나(기본 닫힘, 이 브라우저에 기억). */
  asidePinned: boolean
  setAsidePinned: Dispatch<SetStateAction<boolean>>
  tab: PaneId
  setTab: Dispatch<SetStateAction<PaneId>>
  listView: ListView
  setListView: Dispatch<SetStateAction<ListView>>
}

interface Props {
  workspace: WorkspaceState
  theme: ThemeState
  mode: LayoutMode
  layout: Layout
  onImport: (mode?: ImportMode) => void
}

export function Workbench({ workspace, theme, mode, layout, onImport }: Props) {
  const { me } = useSignedIn()
  const { listOpen, setListOpen, asideOpen, setAsideOpen, asidePinned, tab, setTab, listView, setListView } = layout
  const compact = isCompact(mode)
  // 결재·현황 결재함의 '열기'(/app?record=R-…): 처음 열 때 한 번 읽는다. 있으면 목록 첫 줄을 자동으로 열지 않는다
  const [linkedRecord] = useState(() => recordParam(window.location.search))
  const session = useAnalysisSession({ openFirst: linkedRecord === null })
  const { basis, context: assistantContext, shown: shownContext, change: changeBasis } = useBasis(workspace, session)
  const opens = useOpenOrder(session, compact, setTab)
  const assistant = useAssistant({
    context: assistantContext,
    generation: session.generation,
    onAnalyzed: opens.adopt,
    onRecorded: session.refresh,
  })
  // 결재(기록·승인, docs/records.md): 상세에 보이는 ECN의 상태·이력과 목록의 상태 칩
  const records = useRecords(session.chosen)
  // 통보 기록(1.28.0): 지금 고른 설계변경의 기록에 알림 초안별 '보냄·수령 확인·회신'을 남긴다
  const noticeBridge = useNoticeBridge(session, records, can(me, 'record'))
  const [jsonOpen, setJsonOpen] = useState(false)
  const [detailTab, setDetailTab] = useState<DetailTab>('cost')
  // 문서로 넣기(docs/input.md(문서 접수)): 비서와 같은 맥락(호선·기준일)으로 지도와 대조한다
  const [intakeOpen, setIntakeOpen] = useState(false)
  // 결재 상태 목록 읽기 실패 알림: 닫은 실패는 숨기고, 새로 실패하면 다시 보인다
  const [closedFailure, setClosedFailure] = useState<number | null>(null)
  const active = workspace.active
  const snapshotId = active?.snapshot_id ?? null
  const loginMode = session.health?.auth?.required ?? true
  const approver = can(me, 'approve')
  const evidence = useEvidence(session.select, compact, setTab)
  const dock = useAssistantDock(mode, layout, { input: ASSISTANT_INPUT_ID, toggle: ASSISTANT_TOGGLE_ID })
  const palette = useCommandPalette({
    me,
    mode,
    loginMode,
    listOpen,
    setListOpen,
    dock,
    theme,
    onImport,
    onIntake: () => setIntakeOpen(true),
    onJson: () => setJsonOpen(true),
  })
  const links = useRecordLinks({ session, order: opens, reloadRecords: records.reload, linkedRecord, compact, showTab: setTab })
  const statusUpdate = useStatusUpdate(workspace, session)
  const turns = turnActions({
    entries: assistant.entries,
    adopt: opens.adopt,
    showDetail: dock.showDetail,
    selectNode: evidence.selectNode,
    mode,
    setAsideOpen,
  })

  // 문서 확정 → 그 분석을 상세에(사용자가 고른 화면으로 세대를 올린다)
  const intakeAnalyzed: Parameters<typeof IntakeDialog>[0]['onAnalyzed'] = (request, result) => {
    opens.adopt(request, result, true)
    if (compact) setTab('detail')
    else if (mode === 'desktop') setAsideOpen(false)
  }

  return (
    <NoticeContext.Provider value={noticeBridge}>
      <AppShell
        mode={mode}
        top={
          <>
            <TopBar
              mode={mode}
              context={shownContext}
              health={session.health}
              theme={theme}
              workspace={workspace}
              onImport={onImport}
              listOpen={listOpen}
              onToggleList={() => setListOpen((open) => !open)}
              assistantOpen={dock.shown}
              onToggleAssistant={dock.toggle}
              onSearch={() => palette.setOpen(true)}
              demo={<DemoMenu samples={session.samples} />}
            />
            <NoticeBar notice={workspace.notice} onDismiss={workspace.dismissNotice} />
            <NoticeBar notice={links.notice} onDismiss={links.dismissNotice} />
            <NoticeBar
              notice={records.listFailure !== null && records.listFailure !== closedFailure ? RECORDS_FAILED : null}
              onDismiss={() => setClosedFailure(records.listFailure)}
            />
          </>
        }
        list={{
          title: '설계변경',
          // 머리 개수 = 목록에 보이는 설계변경 전부(샘플 + 아래 '다른 기록', 종료 포함) — 거르기 칸 '전체 + 종료'와 같은 수
          count: basis ? undefined : listedCount(session.samples, records.items) || undefined,
          actions: !basis && session.samples.length > 0 && (
            <ListSortButton view={listView} onView={setListView} compact={compact} />
          ),
          body: (
            <ListPaneBody
              mapBasis={
                basis && active ? { info: active, basis, onBasis: changeBasis, onAssistant: () => dock.open() } : null
              }
              list={{
                samples: session.samples,
                chosen: session.chosen,
                failed: session.listError !== null,
                ready: session.listReady,
                onChoose: opens.choose,
                view: listView,
                onView: setListView,
                compact,
                records: records.items,
                onOpenRecord: links.openRecord,
                snapshotId,
                approver,
                recorder: can(me, 'record') ? me.login_id : null,
              }}
            />
          ),
        }}
        detail={
          <EcnDetail
            session={session}
            compact={compact}
            tab={detailTab}
            onTab={setDetailTab}
            evidenceRequest={evidence.request}
            onEvidence={evidence.selectNode}
            emptyText={basis ? 'AI 비서에 설계변경 입력 → 분석 결과' : undefined}
            records={records}
            me={me}
            snapshotId={snapshotId}
            loginMode={loginMode}
            onOpenRecorded={links.openRecordId}
            today={workspace.list?.today ?? todayKst()}
            canConfirm={can(me, 'record')}
            onStatusUpdate={statusUpdate}
            webMail={workspace.list?.data_mode === 'synthetic'}
          />
        }
        aside={{
          title: ASSISTANT_TITLE,
          description: '설계변경을 문장으로 → 되묻고 분석',
          actions: !jsonOpen && (
            <AsideActions
              onIntake={() => setIntakeOpen(true)}
              intakeReady={assistantContext !== null}
              onReset={assistant.entries.length > 0 ? assistant.reset : null}
              onJson={loginMode ? null : () => setJsonOpen(true)}
              onClose={mode === 'wide' ? dock.close : null}
            />
          ),
          body: (
            <AssistantPanel
              assistant={assistant}
              ready={assistantContext !== null}
              note={
                workspace.list?.data_mode === 'real'
                  ? '실제 데이터 지도 — AI 외부 호출 없이 서버 규칙으로 해석·설명'
                  : null
              }
              shownAnalysisId={session.result?.analysis_id ?? null}
              compact={compact}
              webMail={workspace.list?.data_mode === 'synthetic'}
              onOpenTurn={turns.openTurn}
              onEntity={turns.entityAction}
              json={{
                open: jsonOpen,
                onClose: () => setJsonOpen(false),
                editor: (
                  <RequestEditor
                    draft={session.draft}
                    busy={session.busy}
                    onEdit={session.edit}
                    onRun={session.runDraft}
                  />
                ),
              }}
            />
          ),
        }}
        listOpen={listOpen}
        asideOpen={asideOpen}
        asidePinned={asidePinned}
        onAsideOpen={setAsideOpen}
        tab={tab}
        onTab={setTab}
      />
      <IntakeDialog
        open={intakeOpen}
        onOpenChange={setIntakeOpen}
        context={assistantContext}
        dataMode={workspace.list?.data_mode ?? null}
        aiOn={workspace.list?.llm_external ?? false}
        compact={compact}
        onAnalyzed={intakeAnalyzed}
      />
      <CommandPalette
        open={palette.open}
        onOpenChange={palette.setOpen}
        samples={session.samples}
        onChoose={opens.choose}
        report={session.result}
        onSelectNode={evidence.selectNode}
        actions={palette.actions}
      />
    </NoticeContext.Provider>
  )
}
