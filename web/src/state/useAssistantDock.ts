// AI 비서 칸 열고 닫기: 넓은 화면(1440px 이상)은 펼친 칸, 1024~1439px는 시트, 태블릿은 비서 탭, 휴대폰은 입력창 초점.
// 배치 상태는 App이 가진다(작업 공간이 바뀌어도 그대로).
import { useCallback } from 'react'
import { isCompact, type LayoutMode } from '@/lib/viewport'

/** 비서 칸에 필요한 화면 배치(Workbench Layout의 일부). */
interface DockLayout {
  asideOpen: boolean
  setAsideOpen: (open: boolean) => void
  asidePinned: boolean
  setAsidePinned: (pinned: boolean) => void
  tab: string
  setTab: (tab: 'detail' | 'aside') => void
}

/** 초점을 옮길 요소 ID: 비서 입력창, 위 막대 'AI 비서' 단추. */
interface DockTargets {
  input: string
  toggle: string
}

export interface AssistantDock {
  /** 지금 AI 비서가 보이나: 넓으면 칸, 1024~1439px는 시트, 태블릿은 비서 탭. */
  shown: boolean
  /** 연다. focus면 입력창으로 초점을 옮긴다(문장을 바로 적게). */
  open: (focus?: boolean) => void
  /** 넓은 화면의 칸 닫기. */
  close: () => void
  /** 위 막대 단추·명령 팔레트 'AI 비서 열기/닫기': 보이면 닫고(태블릿은 상세 탭으로), 아니면 연다. */
  toggle: () => void
  /** 비서 칸에서 상세로: 시트는 닫고, 좁은 화면은 상세 탭으로. */
  showDetail: () => void
}

export function useAssistantDock(mode: LayoutMode, layout: DockLayout, targets: DockTargets): AssistantDock {
  const { asideOpen, setAsideOpen, asidePinned, setAsidePinned, tab, setTab } = layout
  const { input, toggle: toggleTarget } = targets
  const compact = isCompact(mode)
  const open = useCallback(
    (focus = true) => {
      if (mode === 'wide') {
        setAsidePinned(true)
        // 칸이 막 그려진 뒤 입력창으로(문장을 바로 적게)
        if (focus) window.requestAnimationFrame(() => document.getElementById(input)?.focus())
      } else if (mode === 'desktop') setAsideOpen(true)
      else if (mode === 'tablet') setTab('aside')
      else if (focus) document.getElementById(input)?.focus()
    },
    [mode, setAsideOpen, setAsidePinned, setTab, input],
  )
  // 넓은 화면의 칸 닫기: 닫기 단추가 칸과 함께 사라지므로 초점은 위 막대 'AI 비서' 단추로
  const close = () => {
    setAsidePinned(false)
    window.requestAnimationFrame(() => document.getElementById(toggleTarget)?.focus())
  }
  const shown = mode === 'wide' ? asidePinned : mode === 'desktop' ? asideOpen : mode === 'tablet' && tab === 'aside'
  const toggle = () => {
    if (!shown) open()
    else if (mode === 'wide') close()
    else if (mode === 'desktop') setAsideOpen(false)
    else setTab('detail')
  }
  const showDetail = useCallback(() => {
    if (mode === 'desktop') setAsideOpen(false)
    if (compact) setTab('detail')
  }, [mode, compact, setAsideOpen, setTab])
  return { shown, open, close, toggle, showDetail }
}
