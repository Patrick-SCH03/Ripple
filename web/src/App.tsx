// Ripple 업무 화면: 작업 공간(지금 쓰는 지도)·밝기·화면 배치·엑셀 가져오기는 여기, 지도마다 따로인 상태(분석 세션·
// AI 비서·분석 기준)는 Workbench. Workbench는 작업 공간 토큰을 key로 그려 지도가 바뀌면 통째로 새로 만든다
// (docs/operations.md(서비스) 6절). 배치(목록 접기·시트·탭·정렬)는 지도가 바뀌어도 그대로 둔다.
import { RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type PaneId } from './components/shell/AppShell'
import { NoticeBar } from './components/shell/NoticeBar'
import { Button } from './components/ui/button'
import { ImportDialog, type ImportMode } from './components/workspace/ImportDialog'
import { DEFAULT_VIEW, type ListView } from './lib/ecnList'
import { safeStorage } from './lib/storage'
import { useTheme } from './lib/theme'
import { useLayoutMode } from './lib/viewport'
import { useWorkspace } from './state/useWorkspace'
import { Workbench } from './Workbench'

const ASSISTANT_PINNED = 'ripple.assistant.pinned'

export default function App() {
  const workspace = useWorkspace()
  const theme = useTheme()
  const mode = useLayoutMode()
  const [importMode, setImportMode] = useState<ImportMode | null>(null)
  const [listOpen, setListOpen] = useState(true)
  const [asideOpen, setAsideOpen] = useState(false)
  // 넓은 화면(1440px 이상)의 AI 비서 칸: 기본은 닫아 가운데 분석에 집중하고, 연 상태는 이 브라우저에 기억한다
  const [asidePinned, setAsidePinned] = useState(() => safeStorage.getItem(ASSISTANT_PINNED) === '1')
  useEffect(() => safeStorage.setItem(ASSISTANT_PINNED, asidePinned ? '1' : '0'), [asidePinned])
  const [tab, setTab] = useState<PaneId>('detail')
  // 목록 정렬·거르기: 좁은 화면에서 탭을 바꿔 목록이 다시 그려져도 유지
  const [listView, setListView] = useState<ListView>(DEFAULT_VIEW)
  const layout = {
    listOpen,
    setListOpen,
    asideOpen,
    setAsideOpen,
    asidePinned,
    setAsidePinned,
    tab,
    setTab,
    listView,
    setListView,
  }

  return (
    <>
      {workspace.key ? (
        <Workbench
          key={workspace.key}
          workspace={workspace}
          theme={theme}
          mode={mode}
          layout={layout}
          onImport={(mode: ImportMode = 'full') => setImportMode(mode)}
        />
      ) : (
        <div className="flex h-dvh flex-col">
          <NoticeBar notice={workspace.notice} onDismiss={workspace.dismissNotice} />
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-sm text-foreground-secondary">
            <p role="status">{workspace.notice ? '지도 목록 불러오기 실패' : '지도 불러오는 중…'}</p>
            {workspace.notice && (
              <Button variant="outline" onClick={workspace.reload}>
                <RotateCw aria-hidden />
                다시 불러오기
              </Button>
            )}
          </div>
        </div>
      )}
      <ImportDialog
        key={importMode ?? 'closed'}
        open={importMode !== null}
        onOpenChange={(open) => !open && setImportMode(null)}
        workspace={workspace}
        mode={importMode ?? 'full'}
      />
    </>
  )
}
