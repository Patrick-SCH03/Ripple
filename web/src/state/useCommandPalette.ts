// 명령 팔레트(Ctrl/⌘+K): 열림 상태와 단축키(한글 입력 상태에서도 잡히도록 key와 물리 키(code)를 함께 본다),
// 화면 동작 목록(권한·화면 폭에 따라 넣고 뺀다).
import { Braces, FileText, FileUp, MessagesSquare, Monitor, Moon, PanelLeft, Sun, type LucideIcon } from 'lucide-react'
import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import type { Me } from '@/api/client'
import { can } from '@/lib/account'
import { THEME_NAMES, type ThemeState } from '@/lib/theme'
import type { LayoutMode } from '@/lib/viewport'
import type { AssistantDock } from './useAssistantDock'

/** 팔레트의 화면 동작 하나(CommandPalette가 그대로 그린다). */
export interface PaletteCommand {
  id: string
  label: string
  icon: LucideIcon
  run: () => void
}

interface Options {
  me: Me
  mode: LayoutMode
  /** 로그인 모드(개발 모드면 요청 JSON 고치기를 넣는다). */
  loginMode: boolean
  listOpen: boolean
  setListOpen: Dispatch<SetStateAction<boolean>>
  dock: Pick<AssistantDock, 'shown' | 'open' | 'toggle'>
  theme: ThemeState
  onImport: (mode: 'full' | 'status') => void
  onIntake: () => void
  onJson: () => void
}

export interface CommandPaletteState {
  open: boolean
  setOpen: Dispatch<SetStateAction<boolean>>
  actions: PaletteCommand[]
}

export function useCommandPalette(options: Options): CommandPaletteState {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
      if (event.code !== 'KeyK' && event.key.toLowerCase() !== 'k') return
      event.preventDefault()
      setOpen((current) => !current)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return { open, setOpen, actions: paletteActions(options) }
}

function paletteActions({
  me,
  mode,
  loginMode,
  listOpen,
  setListOpen,
  dock,
  theme,
  onImport,
  onIntake,
  onJson,
}: Options): PaletteCommand[] {
  return [
    { id: 'intake', label: '문서로 넣기(설계변경 문서·변경 리스트)', icon: FileText, run: onIntake },
    ...(can(me, 'import') ? [{ id: 'import', label: '엑셀 가져오기', icon: FileUp, run: () => onImport('full') }] : []),
    ...(can(me, 'record')
      ? [{ id: 'status-upload', label: '상태 올리기(발주·공정)', icon: FileUp, run: () => onImport('status') }]
      : []),
    ...(mode === 'wide' || mode === 'desktop'
      ? [{ id: 'list', label: listOpen ? '목록 접기' : '목록 펼치기', icon: PanelLeft, run: () => setListOpen((open) => !open) }]
      : []),
    ...(mode !== 'phone'
      ? [{ id: 'assistant', label: dock.shown ? 'AI 비서 닫기' : 'AI 비서 열기', icon: MessagesSquare, run: dock.toggle }]
      : []),
    // 요청 JSON 편집은 개발 모드(로그인 끔)에서만: 운영 화면에는 개발용 단추를 두지 않는다(DESIGN 6절)
    ...(mode !== 'phone' && !loginMode
      ? [
          {
            id: 'json',
            label: '요청 JSON 고치기(개발용)',
            icon: Braces,
            run: () => {
              onJson()
              dock.open(false)
            },
          },
        ]
      : []),
    { id: 'theme-auto', label: `밝기: ${THEME_NAMES.auto}`, icon: Monitor, run: () => theme.choose('auto') },
    { id: 'theme-light', label: `밝기: ${THEME_NAMES.light}`, icon: Sun, run: () => theme.choose('light') },
    { id: 'theme-dark', label: `밝기: ${THEME_NAMES.dark}`, icon: Moon, run: () => theme.choose('dark') },
  ]
}
