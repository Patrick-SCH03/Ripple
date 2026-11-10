// 업무 화면 뼈대(DESIGN.md 5·7절): 위 막대 + ECN 목록 | ECN 상세 | 오른쪽 칸.
// wide: 세 칸(경계는 끌거나 화살표 키로 조절, 크기는 이 브라우저에 기억 — 오른쪽 AI 비서 칸은 위 막대 단추로 열고 닫음, 기본
// 닫힘) · desktop: 목록 + 상세, 오른쪽 칸은 시트 ·
// tablet: 한 칸 + 아래 탭 · phone: 목록·상세 두 탭(조회 전용).
import { FileText, List, MessagesSquare, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useDefaultLayout } from 'react-resizable-panels'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useReturnFocus } from '@/lib/focus'
import { safeStorage } from '@/lib/storage'
import type { LayoutMode } from '@/lib/viewport'
import { PaneHeader } from './PaneHeader'

export type PaneId = 'list' | 'detail' | 'aside'

/** 머리를 뼈대가 그리는 칸(목록·오른쪽 칸). 상세는 자기 머리를 직접 그린다. */
export interface Pane {
  title: string
  count?: number
  /** 시트로 열 때 화면 낭독기에 읽히는 한 줄 설명. */
  description?: string
  /** 머리 오른쪽 동작(예: 새 대화). */
  actions?: ReactNode
  body: ReactNode
}

interface Props {
  mode: LayoutMode
  top: ReactNode
  list: Pane
  detail: ReactNode
  aside: Pane
  listOpen: boolean
  /** 1024~1439px의 AI 비서 시트. */
  asideOpen: boolean
  /** 1440px 이상에서 AI 비서 칸을 펼쳐 두었나(닫으면 가운데 상세가 넓어진다). */
  asidePinned: boolean
  onAsideOpen: (open: boolean) => void
  tab: PaneId
  onTab: (tab: PaneId) => void
}

export function AppShell(props: Props) {
  const split = props.mode === 'wide' || props.mode === 'desktop'
  return (
    <div className="flex h-dvh flex-col overflow-clip">
      {props.top}
      {split ? <SplitPanes {...props} /> : <TabbedPanes {...props} />}
    </div>
  )
}

function ListPane({ pane }: { pane: Pane }) {
  return (
    <nav aria-label={`${pane.title} 목록`} className="flex h-full flex-col bg-surface">
      <PaneHeader title={pane.title} count={pane.count} actions={pane.actions} />
      <div className="min-h-0 flex-1 overflow-y-auto">{pane.body}</div>
    </nav>
  )
}

function AsidePane({ pane }: { pane: Pane }) {
  return (
    <aside aria-label={pane.title} className="flex h-full flex-col bg-surface">
      <PaneHeader title={pane.title} actions={pane.actions} />
      <div className="min-h-0 flex-1 overflow-y-auto">{pane.body}</div>
    </aside>
  )
}

function SplitPanes({ mode, list, detail, aside, listOpen, asideOpen, asidePinned, onAsideOpen }: Props) {
  const wide = mode === 'wide'
  const showAside = wide && asidePinned
  const panelIds = [...(listOpen ? ['list'] : []), 'detail', ...(showAside ? ['aside'] : [])]
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: `ripple.panes.${mode}`, panelIds, storage: safeStorage })
  const returnFocus = useReturnFocus(asideOpen)
  return (
    <>
      {/* 칸을 열고 닫아도 그룹을 다시 만들지 않는다: 다시 만들면 상세가 처음부터 그려져 읽던 자리(스크롤)를 잃는다.
          칸 구성마다 크기는 panelIds로 따로 기억한다 */}
      <ResizablePanelGroup
        orientation="horizontal"
        defaultLayout={defaultLayout}
        onLayoutChanged={onLayoutChanged}
        className="min-h-0 flex-1"
      >
        {listOpen && (
          <>
            <ResizablePanel id="list" defaultSize="380px" minSize="280px" maxSize="520px" groupResizeBehavior="preserve-pixel-size">
              <ListPane pane={list} />
            </ResizablePanel>
            <ResizableHandle aria-label="목록 폭 조절" />
          </>
        )}
        <ResizablePanel id="detail" minSize="480px">
          <main className="flex h-full min-w-0 flex-col bg-surface">{detail}</main>
        </ResizablePanel>
        {showAside && (
          <>
            <ResizableHandle aria-label={`${aside.title} 폭 조절`} />
            <ResizablePanel id="aside" defaultSize="400px" minSize="320px" maxSize="560px" groupResizeBehavior="preserve-pixel-size">
              <AsidePane pane={aside} />
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
      {!wide && (
        <Sheet open={asideOpen} onOpenChange={onAsideOpen}>
          <SheetContent
            side="right"
            onCloseAutoFocus={returnFocus}
            className="gap-0 p-0 data-[side=right]:w-[400px] data-[side=right]:max-w-[calc(100vw-48px)] data-[side=right]:sm:max-w-[400px]"
          >
            <SheetHeader className="h-11 shrink-0 flex-row items-center gap-2 border-b border-border px-4 py-0 pr-12">
              <SheetTitle className="text-md font-semibold">{aside.title}</SheetTitle>
              {aside.description && <SheetDescription className="sr-only">{aside.description}</SheetDescription>}
              {aside.actions && <div className="ml-auto flex items-center gap-1">{aside.actions}</div>}
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto">{aside.body}</div>
          </SheetContent>
        </Sheet>
      )}
    </>
  )
}

const TAB_ICONS: Record<PaneId, LucideIcon> = { list: List, detail: FileText, aside: MessagesSquare }

function TabbedPanes({ mode, list, detail, aside, tab, onTab }: Props) {
  // 휴대전화는 조회·승인만(DESIGN.md 7절): AI 비서 칸은 태블릿부터
  const tabs: PaneId[] = mode === 'phone' ? ['list', 'detail'] : ['list', 'detail', 'aside']
  const active = tabs.includes(tab) ? tab : 'detail'
  const labels: Record<PaneId, string> = { list: '목록', detail: '상세', aside: aside.title }
  return (
    <>
      <div className="min-h-0 flex-1 overflow-clip">
        {active === 'list' && <ListPane pane={list} />}
        {active === 'detail' && <main className="flex h-full min-w-0 flex-col bg-surface">{detail}</main>}
        {active === 'aside' && <AsidePane pane={aside} />}
      </div>
      <nav
        aria-label="화면 전환"
        className="grid shrink-0 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)]"
        style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
      >
        {tabs.map((id) => {
          const Icon = TAB_ICONS[id]
          return (
            <button
              key={id}
              type="button"
              aria-current={id === active ? 'page' : undefined}
              onClick={() => onTab(id)}
              className="flex h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium text-foreground-secondary aria-[current=page]:text-primary"
            >
              <Icon aria-hidden className="size-5" />
              {labels[id]}
            </button>
          )
        })}
      </nav>
    </>
  )
}
