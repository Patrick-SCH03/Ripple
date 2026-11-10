// 화면 밝기: 자동(시스템) · 밝게 · 어둡게. 고른 값은 이 브라우저에만 저장한다.
// index.html 머리의 스크립트가 같은 규칙(KEY, resolveTheme)으로 첫 그림 전에 적용한다(깜빡임 방지).
import { useCallback, useLayoutEffect, useState, useSyncExternalStore } from 'react'
import { safeStorage } from './storage'

export type ThemeChoice = 'auto' | 'light' | 'dark'
export type Theme = 'light' | 'dark'

export const THEME_CHOICES: readonly ThemeChoice[] = ['auto', 'light', 'dark']
export const THEME_NAMES: Record<ThemeChoice, string> = { auto: '자동', light: '밝게', dark: '어둡게' }
export const THEME_KEY = 'ripple.theme'
const SYSTEM_DARK = '(prefers-color-scheme: dark)'

/** 고른 값과 시스템 설정 → 실제로 그릴 밝기. */
export function resolveTheme(choice: ThemeChoice, systemDark: boolean): Theme {
  if (choice === 'auto') return systemDark ? 'dark' : 'light'
  return choice
}

/** 저장된 값을 읽는다. 없거나 모르는 값, 저장소를 못 쓰면 밝게(발표장·현장 태블릿 기준 — DESIGN.md 3절). */
export function readChoice(storage: Pick<Storage, 'getItem'> | undefined): ThemeChoice {
  try {
    const saved = storage?.getItem(THEME_KEY)
    return THEME_CHOICES.find((choice) => choice === saved) ?? 'light'
  } catch {
    return 'light'
  }
}

function subscribeSystem(onChange: () => void): () => void {
  const query = window.matchMedia(SYSTEM_DARK)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

const systemDark = () => window.matchMedia(SYSTEM_DARK).matches

function applyTheme(theme: Theme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.dataset.theme = theme
}

/**
 * 이 화면이 떠 있는 동안은 밝게만(소개 화면 · 인쇄용 판단 리포트). 떠나면 고른 밝기로 되돌린다
 * (로그인 화면은 useTheme을 부르지 않으니 여기서 되돌려야 한다). layout effect라 되돌림이 다음 화면의 적용보다 먼저 끝난다
 * (리포트 → 뒤로 → 소개에서 순서가 꼬이지 않게). 소개 화면의 첫 그림은 theme-init.js가 같은 규칙으로 밝게 둔다.
 */
export function useLightOnly(): void {
  useLayoutEffect(() => {
    applyTheme('light')
    return () => {
      applyTheme(resolveTheme(readChoice(safeStorage), systemDark()))
    }
  }, [])
}

export interface ThemeState {
  choice: ThemeChoice
  theme: Theme
  choose: (choice: ThemeChoice) => void
}

export function useTheme(): ThemeState {
  const [choice, setChoice] = useState<ThemeChoice>(() => readChoice(safeStorage))
  const theme = resolveTheme(choice, useSyncExternalStore(subscribeSystem, systemDark))

  // 그래프가 색 토큰을 읽기 전에(자식의 useEffect보다 먼저) 바뀌도록 layout effect로 적용한다
  useLayoutEffect(() => applyTheme(theme), [theme])

  const choose = useCallback((next: ThemeChoice) => {
    setChoice(next)
    safeStorage.setItem(THEME_KEY, next)
  }, [])

  return { choice, theme, choose }
}
