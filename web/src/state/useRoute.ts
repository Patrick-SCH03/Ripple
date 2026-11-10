// 주소 구독(history API): 뒤로·앞으로(popstate)와 navigate가 보내는 이벤트를 같은 값으로 읽는다.
import { useSyncExternalStore } from 'react'

const EVENT = 'ripple:navigate'

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange)
  window.addEventListener(EVENT, onChange)
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(EVENT, onChange)
  }
}

function read(): string {
  return `${window.location.pathname}${window.location.search}`
}

/** 같은 사이트 안 경로로만 옮긴다(소개 · 로그인 · 업무 화면). replace면 뒤로 가기에 남기지 않는다. */
export function navigate(path: string, { replace = false }: { replace?: boolean } = {}): void {
  if (read() === path) return
  if (replace) window.history.replaceState(null, '', path)
  else window.history.pushState(null, '', path)
  window.dispatchEvent(new Event(EVENT))
}

export function useLocation(): { pathname: string; search: string } {
  const href = useSyncExternalStore(subscribe, read)
  const at = href.indexOf('?')
  return at < 0 ? { pathname: href, search: '' } : { pathname: href.slice(0, at), search: href.slice(at) }
}
