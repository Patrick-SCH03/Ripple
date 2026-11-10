// 파급 그래프 전체 화면(그래프 + 근거): 브라우저 전체 화면을 먼저 쓰고, 막혀 있으면(앱 안 브라우저·권한) 창 안을 가득
// 채운다. 상태는 그래프를 다시 그려도(다시 보기) 남도록 그래프 칸 바깥(GraphWorkspace)이 든다.
import { type RefObject, useCallback, useEffect, useState } from 'react'

export interface Fullscreen {
  /** 브라우저 전체 화면이거나 창 안 채우기 중. */
  full: boolean
  /** 창 안 채우기 중(브라우저 전체 화면이 막혀 대신 쓰는 중). */
  overlay: boolean
  toggle: () => void
}

/**
 * frame = 전체 화면으로 키울 요소. canClose = Esc로 창 안 채우기를 닫아도 되는가(카드를 고른 동안의 Esc는 고른 것을 푸는
 * 데 먼저 쓴다). 브라우저 전체 화면의 Esc는 브라우저가 처리한다.
 */
export function useFullscreen(frame: RefObject<HTMLElement | null>, canClose: () => boolean): Fullscreen {
  const [native, setNative] = useState(false)
  const [overlay, setOverlay] = useState(false)

  useEffect(() => {
    const sync = () => {
      const on = document.fullscreenElement !== null && document.fullscreenElement === frame.current
      setNative(on)
      if (on) setOverlay(false) // 늦게 허락된 브라우저 전체 화면이 창 안 채우기를 대신한다
    }
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [frame])

  useEffect(() => {
    if (!overlay) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && canClose()) setOverlay(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlay, canClose])

  const toggle = useCallback(() => {
    const element = frame.current
    if (overlay) setOverlay(false)
    else if (document.fullscreenElement === element && element) void document.exitFullscreen()
    else if (element?.requestFullscreen && !document.fullscreenElement) {
      element.requestFullscreen().catch(() => setOverlay(true))
      // 거절도 허락도 오지 않는 환경(앱 안 브라우저 등)에서는 잠깐 뒤 창 안 채우기로
      window.setTimeout(() => {
        if (document.fullscreenElement !== element) setOverlay(true)
      }, 400)
    } else setOverlay(true)
  }, [frame, overlay])

  return { full: native || overlay, overlay, toggle }
}
