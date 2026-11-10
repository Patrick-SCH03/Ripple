// DESIGN.md 색 토큰(CSS 변수)을 읽어 three 재질에 쓴다. 밝게·어둡게가 바뀌면(html의 class·data-theme) 다시 읽는다.
import { useEffect, useState } from 'react'
import type { Severity } from '@/api/client'

const NAMES = {
  surface: '--surface',
  canvas: '--canvas',
  muted: '--muted',
  borderSubtle: '--border-subtle',
  borderStrong: '--border-strong',
  text: '--text-primary',
  textSecondary: '--text-secondary',
  textMuted: '--text-muted',
  primary: '--primary',
  warning: '--warning',
  danger: '--danger',
  focus: '--focus-ring',
} as const

export type Tokens = Record<keyof typeof NAMES, string> & { dark: boolean }

function read(): Tokens {
  const style = getComputedStyle(document.documentElement)
  const entries = Object.entries(NAMES).map(([key, name]) => [key, style.getPropertyValue(name).trim() || '#888888'])
  return { ...(Object.fromEntries(entries) as Record<keyof typeof NAMES, string>), dark: document.documentElement.classList.contains('dark') }
}

export function useTokens(): Tokens {
  const [tokens, setTokens] = useState(read)
  useEffect(() => {
    const observer = new MutationObserver(() => setTokens(read()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] })
    return () => observer.disconnect()
  }, [])
  return tokens
}

/** 움직임 줄이기 설정(켜져 있으면 카메라 이동을 애니메이션 없이 바로). */
export function useReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const media = window.matchMedia?.(query)
    if (!media) return
    const onChange = () => setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return reduced
}

/** 영향 단계 색(2D 카드 테두리와 같은 토큰): 높음 danger · 보통 warning · 낮음 primary · 정보·영향 없음 border-strong. */
export function severityColor(severity: Severity | null, tokens: Tokens): string {
  if (severity === 'high') return tokens.danger
  if (severity === 'medium') return tokens.warning
  if (severity === 'low') return tokens.primary
  return tokens.borderStrong
}
