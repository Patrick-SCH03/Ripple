// 시연 실행기의 화면 조작(DOM): 요소 찾기 · 나타날/사라질 때까지 기다리기 · 부드러운 스크롤 · 단추 누르기 · 탭 바꾸기 ·
// 한 글자씩 넣기. 모든 기다림은 AbortSignal로 끊긴다(멈추기·화면 이동). 셀렉터는 lib/demoScenarios.ts가 정한다.
import type { DemoTarget } from '@/lib/demoScenarios'

/** 사람이 멈췄거나 화면이 사라져 실행을 끊음. */
export class DemoAborted extends Error {}
/** 제한 시간 안에 요소가 나타나지 않음 — 띠에 '여기서 멈췄어요'. */
export class DemoStuck extends Error {}

const POLL_MS = 100
/** 탭이 가려져 rAF가 멈추면 이만큼 뒤에 setTimeout으로 넘어간다(조용히 멈춰 있지 않게). */
const FRAME_FALLBACK_MS = 200

/**
 * 멈추기로 끊을 수 있는 기다림. start는 끝날 때 부를 done을 받아 타이머를 걸고 그 정리 함수를 돌려준다 — 끝나거나 끊기면
 * 정리하고 멈추기 듣기를 뗀다. 이미 멈췄으면 바로 DemoAborted.
 */
function abortable(signal: AbortSignal, start: (done: () => void) => () => void): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DemoAborted())
      return
    }
    let cleanup: () => void = () => undefined
    const finish = (then: () => void) => {
      cleanup()
      signal.removeEventListener('abort', abort)
      then()
    }
    const abort = () => finish(() => reject(new DemoAborted()))
    cleanup = start(() => finish(resolve))
    signal.addEventListener('abort', abort, { once: true })
  })
}

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return abortable(signal, (done) => {
    const timer = window.setTimeout(done, ms)
    return () => window.clearTimeout(timer)
  })
}

/** 다음 화면 그리기까지(멈추기를 들으며, rAF가 안 오면 FRAME_FALLBACK_MS 뒤에). */
function nextFrame(signal: AbortSignal): Promise<void> {
  return abortable(signal, (done) => {
    const frame = window.requestAnimationFrame(done)
    const timer = window.setTimeout(done, FRAME_FALLBACK_MS)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearTimeout(timer)
    }
  })
}

/** 창 이벤트를 듣고, 떼는 함수를 돌려준다(붙일 때와 같은 capture로 뗀다). */
export function listen<K extends keyof WindowEventMap>(
  type: K,
  handler: (event: WindowEventMap[K]) => void,
  options: boolean | AddEventListenerOptions = false,
): () => void {
  window.addEventListener(type, handler, options)
  return () => window.removeEventListener(type, handler, options)
}

function visible(element: Element): boolean {
  const rect = element.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) return false
  const style = getComputedStyle(element)
  return style.visibility !== 'hidden' && style.display !== 'none'
}

function enabled(element: Element): boolean {
  return !(element as HTMLButtonElement).disabled && element.getAttribute('aria-disabled') !== 'true'
}

function textMatches(element: Element, want: DemoTarget): boolean {
  if (!want.text) return true
  const text = (element.textContent ?? '').trim()
  return want.exact ? text === want.text : text.includes(want.text)
}

/** 보이는 요소 가운데 글이 맞는 것(여럿이면 가장 작은 것 — 글을 가진 가장 안쪽 요소). */
export function findTarget(want: DemoTarget, options: { usable?: boolean; except?: ReadonlySet<Element> } = {}) {
  const matches = Array.from(document.querySelectorAll<HTMLElement>(want.target)).filter(
    (element) =>
      visible(element) &&
      textMatches(element, want) &&
      (!options.usable || enabled(element)) &&
      !options.except?.has(element),
  )
  if (matches.length === 0) return null
  const area = (element: Element) => {
    const rect = element.getBoundingClientRect()
    return rect.width * rect.height
  }
  return matches.reduce((best, element) => (area(element) < area(best) ? element : best))
}

/** 지금 화면에 있는 같은 모양의 요소들(동작 뒤 '새로 나타난 것'을 가르려고). */
export function snapshot(want: DemoTarget): Set<Element> {
  return new Set(Array.from(document.querySelectorAll(want.target)))
}

interface WaitOptions {
  timeout: number
  signal: AbortSignal
  usable?: boolean
  except?: ReadonlySet<Element>
  /** 이 요소(오류 알림·되묻는 답)가 새로 보이면 기다리지 않고 null. */
  failIf?: string
  /** failIf 가운데 동작 전부터 있던 것(세지 않음). */
  failStale?: ReadonlySet<Element>
}

/** 나타날 때까지 기다린다. 제한 시간을 넘거나 오류 알림이 보이면 null. */
export async function appear(want: DemoTarget, options: WaitOptions): Promise<HTMLElement | null> {
  const end = performance.now() + options.timeout
  for (;;) {
    const found = findTarget(want, options)
    if (found) return found
    if (performance.now() >= end) return null
    if (options.failIf && findTarget({ target: options.failIf }, { except: options.failStale })) return null
    await sleep(POLL_MS, options.signal)
  }
}

/** 사라질 때까지 기다린다. 제한 시간 안에 사라졌으면 true. */
export async function vanish(want: DemoTarget, options: WaitOptions): Promise<boolean> {
  const end = performance.now() + options.timeout
  while (findTarget(want)) {
    if (performance.now() >= end) return false
    await sleep(POLL_MS, options.signal)
  }
  return true
}

/** 요소를 화면 안으로(움직임 줄이기면 바로) 옮기고 스크롤이 멈출 때까지 기다린다. */
export async function reveal(
  element: Element,
  block: 'start' | 'center',
  { reduced, settle, signal }: { reduced: boolean; settle: number; signal: AbortSignal },
): Promise<void> {
  // 화면보다 큰 요소는 위끝을 맞춘다(가운데로 두면 위가 잘린다)
  const tall = element.getBoundingClientRect().height > window.innerHeight * 0.7
  element.scrollIntoView({ block: tall ? 'start' : block, inline: 'nearest', behavior: reduced ? 'auto' : 'smooth' })
  const end = performance.now() + settle
  let last = Number.NaN
  let still = 0
  while (performance.now() < end && still < 4) {
    await nextFrame(signal)
    const top = element.getBoundingClientRect().top
    still = Math.abs(top - last) < 0.5 ? still + 1 : 0
    last = top
  }
}

/** Radix 탭은 click()으로 바뀌지 않는다 — 왼쪽 단추 누름(mousedown)을 보낸다. */
export function pressTab(element: HTMLElement): void {
  const init = { bubbles: true, cancelable: true, button: 0, view: window }
  element.dispatchEvent(new PointerEvent('pointerdown', { ...init, pointerType: 'mouse' }))
  element.dispatchEvent(new MouseEvent('mousedown', init))
  element.dispatchEvent(new PointerEvent('pointerup', { ...init, pointerType: 'mouse' }))
  element.dispatchEvent(new MouseEvent('mouseup', init))
}

/** 제어 입력 칸에 한 글자씩 넣는다(React가 바뀐 값을 읽게 원래 value setter + input 이벤트). 끊기면 원래 글로 돌린다. */
export async function typeInto(element: HTMLElement, value: string, perChar: number, signal: AbortSignal): Promise<void> {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  if (!setter) throw new DemoStuck('입력 칸에 글 넣기 실패')
  const put = (text: string) => {
    setter.call(element, text)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  }
  const original = (element as HTMLTextAreaElement).value
  element.focus({ preventScroll: true })
  try {
    put('')
    for (let at = 1; at <= value.length; at++) {
      put(value.slice(0, at))
      await sleep(perChar, signal)
    }
  } catch (error) {
    if (error instanceof DemoAborted) put(original)
    throw error
  }
}
