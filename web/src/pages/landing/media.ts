// 소개 화면의 폭 판단(DESIGN.md 12절): CSS 중단점과 같은 미디어 쿼리 하나로 정한다. 창 폭 숫자(innerWidth)로 따로 재면
// 브라우저 확대(110%·125%…)의 소수 폭과 브라우저 글꼴 크기 설정(rem 중단점)에서 CSS와 어긋나고, 바뀜 알림은 쿼리 결과가
// 바뀔 때만 오므로 어긋난 채로 창을 줄여도 배치가 그대로 남는다. 그래서 값(matches)과 알림(change)을 같은 쿼리에서 받는다.
import { useSyncExternalStore } from 'react'

/**
 * 'lg 이상'(Tailwind 기본 lg = 64rem, 글꼴 16px이면 1024px) — CSS의 lg: 와 같은 쿼리. 둘러보기 배치를 가른다.
 * index.css @theme가 --breakpoint-lg를 바꾸면 이 값도 함께 바꾼다.
 */
export const LG_QUERY = '(min-width: 64rem)'

type MediaList = Pick<MediaQueryList, 'matches' | 'addEventListener' | 'removeEventListener'>
type MatchMedia = (query: string) => MediaList | null

const windowMatch: MatchMedia = (query) =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) : null

export interface MediaStore {
  subscribe: (onChange: () => void) => () => void
  getSnapshot: () => boolean
}

/** 쿼리 하나의 알림 구독과 값. matchMedia가 없으면(서버 그리기·옛 환경) 늘 거짓이고 알림도 없다. */
export function mediaStore(query: string, match: MatchMedia = windowMatch): MediaStore {
  return {
    subscribe(onChange) {
      const list = match(query)
      list?.addEventListener('change', onChange)
      return () => list?.removeEventListener('change', onChange)
    },
    getSnapshot: () => match(query)?.matches ?? false,
  }
}

const LG = mediaStore(LG_QUERY)

/** 지금 폭이 CSS lg 이상인가. 창 크기·확대·글꼴 크기가 바뀌어 쿼리 결과가 바뀌면 다시 그린다. */
export function useLg(): boolean {
  return useSyncExternalStore(LG.subscribe, LG.getSnapshot, () => false)
}
