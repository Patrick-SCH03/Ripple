// 화면 폭 → 배치 모드(DESIGN.md 7절). 패널 안의 밀도는 뷰포트가 아니라 컨테이너 폭으로 정한다.
import { useSyncExternalStore } from 'react'

/** wide: 3분할 · desktop: 목록 + 상세, 입력은 시트 · tablet: 한 패널 + 아래 탭 · phone: 조회만. */
export type LayoutMode = 'wide' | 'desktop' | 'tablet' | 'phone'

/** 모드가 시작되는 최소 폭(px). */
export const MODE_MIN_WIDTH = { wide: 1440, desktop: 1024, tablet: 768 } as const

export function layoutOf(width: number): LayoutMode {
  if (width >= MODE_MIN_WIDTH.wide) return 'wide'
  if (width >= MODE_MIN_WIDTH.desktop) return 'desktop'
  if (width >= MODE_MIN_WIDTH.tablet) return 'tablet'
  return 'phone'
}

/** 그래프 대신 들여쓴 영향 목록을 쓰는 좁은 모드(태블릿·휴대전화). */
export const isCompact = (mode: LayoutMode): boolean => mode === 'tablet' || mode === 'phone'

const query = (px: number) => `(min-width: ${px}px)`
const QUERIES = Object.values(MODE_MIN_WIDTH).map(query)

/**
 * 지금 모드를 바뀜 알림과 같은 미디어 쿼리 결과로 정한다. 창 폭 숫자(innerWidth, 정수)로 따로 재면 브라우저 확대
 * (110%·125%…)의 소수 폭에서 쿼리와 어긋나고, 알림은 쿼리 결과가 바뀔 때만 오므로 어긋난 채로 창을 줄여도 모드가 남는다.
 */
export function layoutOfQueries(matches: (query: string) => boolean): LayoutMode {
  if (matches(query(MODE_MIN_WIDTH.wide))) return 'wide'
  if (matches(query(MODE_MIN_WIDTH.desktop))) return 'desktop'
  if (matches(query(MODE_MIN_WIDTH.tablet))) return 'tablet'
  return 'phone'
}

function subscribe(onChange: () => void): () => void {
  const lists = QUERIES.map((text) => window.matchMedia(text))
  lists.forEach((list) => list.addEventListener('change', onChange))
  return () => lists.forEach((list) => list.removeEventListener('change', onChange))
}

export function useLayoutMode(): LayoutMode {
  return useSyncExternalStore(subscribe, () => layoutOfQueries((text) => window.matchMedia(text).matches))
}
