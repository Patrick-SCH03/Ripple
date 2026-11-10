// 배포 뒤 옛 화면의 늦게 불러오는 묶음(assets/*.js)이 사라지면 Vite가 'vite:preloadError'를 낸다. 그대로 두면
// 업무 화면이 흰 화면으로 멈추므로 새 index.html을 받도록 한 번 새로 고친다. 새로 고친 뒤에도 같은 오류가 곧바로
// 다시 나면(진짜 없는 파일) 되풀이하지 않고 오류를 그대로 둔다.
const KEY = 'ripple.reloadedForChunk'
export const RELOAD_GAP_MS = 60_000

/** 마지막으로 새로 고친 때(ms, 없으면 null)에서 지금 새로 고쳐도 되는가. */
export function shouldReload(lastAt: number | null, now: number): boolean {
  return lastAt === null || !Number.isFinite(lastAt) || now - lastAt > RELOAD_GAP_MS || now < lastAt
}

function readLast(): number | null {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    return raw === null ? null : Number(raw)
  } catch {
    return null
  }
}

export function reloadOnStaleChunks(): void {
  window.addEventListener('vite:preloadError', (event) => {
    const now = Date.now()
    if (!shouldReload(readLast(), now)) return
    try {
      window.sessionStorage.setItem(KEY, String(now))
    } catch {
      return // 기록할 수 없으면 되풀이를 막을 수 없어 새로 고치지 않는다
    }
    event.preventDefault()
    window.location.reload()
  })
}
