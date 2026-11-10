// 위 막대: 목록 접기 · Ripple · 호선·기준일 · 시연(넓은 화면, components/demo) · 찾기(Ctrl+K) · AI 비서(넓으면 칸 열고 닫기, 좁으면 시트) ·
// 결재·현황(관리자) · 지도(이름·데이터 종류, 전환·가져오기) · 밝기 · 사용자(이름·역할, 비밀번호·구성원 관리·로그아웃).
import { ClipboardCheck, MessagesSquare, PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Health } from '@/api/client'
import { UserMenu } from '@/components/account/UserMenu'
import { BrandMark } from '@/components/common/BrandMark'
import { Button } from '@/components/ui/button'
import { can } from '@/lib/account'
import { cn } from '@/lib/utils'
import { ASSISTANT_TOGGLE_ID } from '@/lib/domIds'
import { formatDay, shortcutLabel } from '@/lib/format'
import { MANAGE_PATH } from '@/lib/route'
import { useSignedIn } from '@/state/sessionContext'
import { navigate } from '@/state/useRoute'
import type { RequestContext } from '@/lib/request'
import type { ThemeState } from '@/lib/theme'
import type { LayoutMode } from '@/lib/viewport'
import type { ImportMode } from '@/components/workspace/ImportDialog'
import type { WorkspaceState } from '@/state/useWorkspace'
import { MapMenu } from './MapMenu'
import { ThemeMenu } from './ThemeMenu'

interface Props {
  mode: LayoutMode
  context: RequestContext | null
  health: Health | null
  theme: ThemeState
  workspace: WorkspaceState
  onImport: (mode?: ImportMode) => void
  listOpen: boolean
  onToggleList: () => void
  /** AI 비서 칸(1440px 이상)·시트(1024~1439px)가 열려 있나. */
  assistantOpen: boolean
  /** 넓은 화면은 칸을 열고 닫고, 1024~1439px는 시트를 연다. */
  onToggleAssistant: () => void
  onSearch: () => void
  /** '시연' 단추(시나리오 자동 실행): 목록·상세가 나란한 넓은 화면에서만 그린다(좁은 화면은 배치·셀렉터가 다름). */
  demo?: ReactNode
}

export function TopBar(props: Props) {
  const { mode, context, health, theme, workspace, onImport, listOpen, onToggleList, assistantOpen, onToggleAssistant, onSearch } =
    props
  const split = mode === 'wide' || mode === 'desktop'
  const approver = can(useSignedIn().me, 'approve')
  return (
    <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border bg-surface px-2 md:gap-2 md:px-3">
      {split && (
        <Button variant="ghost" size="icon" aria-label={listOpen ? '목록 접기' : '목록 펼치기'} onClick={onToggleList}>
          {listOpen ? <PanelLeftClose aria-hidden /> : <PanelLeftOpen aria-hidden />}
        </Button>
      )}
      <div className="flex shrink-0 items-center gap-2 px-1">
        <BrandMark size={22} className="shrink-0" />
        {/* 휴대폰 폭은 단추가 많아이름 글자를 빼고 표지만 — 위 막대가 화면 밖으로 밀리지 않게 */}
        <span className="hidden text-md font-semibold tracking-tight sm:inline">Ripple</span>
      </div>
      {context && mode !== 'phone' && (context.shipIds.length > 0 || context.asOf) && (
        <p className="ml-2 min-w-0 truncate text-sm text-foreground-secondary">
          {context.shipIds.length > 0 && <span className="font-mono">{context.shipIds.join(', ')}</span>}
          {context.shipIds.length > 0 && context.asOf && <span aria-hidden> · </span>}
          {context.asOf && <span>기준일 {formatDay(context.asOf)}</span>}
        </p>
      )}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {split && props.demo}
        <Button
          variant="outline"
          onClick={onSearch}
          aria-label="찾기"
          aria-keyshortcuts="Control+K Meta+K"
          className="text-foreground-secondary"
        >
          <Search aria-hidden />
          {mode !== 'phone' && <span>찾기</span>}
          {split && (
            <kbd
              // 1024~1439px는 큰 글자로 위 막대가 넘쳐 단축키 표시는 뺀다(Ctrl+K는 그대로 동작)
              className={cn(
                'ml-2 rounded-sm border border-border bg-muted px-1 font-sans text-xs text-foreground-secondary',
                mode === 'desktop' && 'hidden',
              )}
            >
              {shortcutLabel('K', navigator.platform)}
            </kbd>
          )}
        </Button>
        {split && (
          <Button
            id={ASSISTANT_TOGGLE_ID}
            variant={assistantOpen ? 'secondary' : 'outline'}
            onClick={onToggleAssistant}
            aria-pressed={mode === 'wide' ? assistantOpen : undefined}
            // 1024~1439px는 칸을 켜고 끄는 게 아니라 시트를 연다 — 열림 상태는 aria-expanded로
            aria-expanded={mode === 'wide' ? undefined : assistantOpen}
            title={mode === 'wide' && assistantOpen ? 'AI 비서 닫기' : 'AI 비서 열기'}
            data-testid="assistant-toggle"
          >
            <MessagesSquare aria-hidden />
            AI 비서
          </Button>
        )}
        {approver && (
          <Button
            variant="outline"
            onClick={() => navigate(MANAGE_PATH)}
            aria-label="결재·현황"
            title="결재·현황(결재함·현황·성과)"
            data-testid="to-manage"
          >
            <ClipboardCheck aria-hidden />
            {mode !== 'phone' && <span>결재·현황</span>}
          </Button>
        )}
        <MapMenu mode={mode} workspace={workspace} onImport={onImport} />
        <ThemeMenu theme={theme} health={health} />
        <UserMenu mode={mode} />
      </div>
    </header>
  )
}
