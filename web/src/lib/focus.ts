// 트리거 부품 없이 상태로 여는 대화상자·시트(Ctrl+K, 위 막대 버튼)는 Radix가 닫힌 뒤 초점을 돌려줄 자리를 모른다.
// 열릴 때 초점이 있던 곳을 기억했다가 닫힐 때 돌려준다(WCAG 2.4.3 초점 순서).
import { useCallback, useLayoutEffect, useRef } from 'react'

/** 대화상자 내용의 onCloseAutoFocus에 넘길 처리기. */
export function useReturnFocus(open: boolean): (event: Event) => void {
  const opener = useRef<HTMLElement | null>(null)

  // Radix가 대화상자 안으로 초점을 옮기기(자식의 useEffect) 전에 기억한다
  useLayoutEffect(() => {
    if (open) opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
  }, [open])

  return useCallback((event: Event) => {
    event.preventDefault()
    const active = document.activeElement
    // 고른 동작이 초점을 다른 곳(예: 요청 JSON 입력)으로 옮겼으면 그대로 둔다
    if (active && active !== document.body && !active.closest('[role="dialog"]')) return
    opener.current?.focus()
  }, [])
}
