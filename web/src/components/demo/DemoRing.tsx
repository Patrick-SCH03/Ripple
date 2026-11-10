// 시연 강조 테두리: 지금 단계의 요소를 둥근 테두리로 감싼다. 요소가 스크롤·배치로 움직여도 매 프레임 따라가고(다시 그리기
// 없이 style만), 다음 요소로 넘어갈 때는 미끄러지듯 옮긴다. 누르는 순간(press가 늘면) 한 번 옅게 채운다.
// 움직임 줄이기 설정이면 index.css의 전역 규칙이 전환을 없앤다(바로 옮김).
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

const PAD = 6
const EDGE = 2
const GLIDE_MS = 320
const PRESS_MS = 280
const GLIDE = `transform ${GLIDE_MS}ms cubic-bezier(.4,0,.2,1), width ${GLIDE_MS}ms cubic-bezier(.4,0,.2,1), height ${GLIDE_MS}ms cubic-bezier(.4,0,.2,1), opacity 200ms ease`

interface Props {
  target: Element | null
  /** 누를 때마다 늘어나는 번호. */
  press: number
}

export function DemoRing({ target, press }: Props) {
  const ring = useRef<HTMLDivElement>(null)
  const had = useRef(false)

  useEffect(() => {
    const element = ring.current
    if (!element) return
    if (!target) {
      had.current = false
      element.style.transition = 'opacity 200ms ease'
      element.style.opacity = '0'
      return
    }
    // 처음 나타날 때는 제자리에서 옅게 떠오르고, 이어지는 단계는 앞 자리에서 미끄러져 온다
    element.style.transition = had.current ? GLIDE : 'opacity 200ms ease'
    had.current = true
    const settle = window.setTimeout(() => (element.style.transition = 'opacity 200ms ease'), GLIDE_MS)
    let frame = 0
    const follow = () => {
      const rect = target.getBoundingClientRect()
      // 화면 밖으로 넘친 쪽은 화면 끝에서 자른다(테두리가 늘 보이게)
      const left = Math.max(rect.left - PAD, EDGE)
      const top = Math.max(rect.top - PAD, EDGE)
      const right = Math.min(rect.right + PAD, window.innerWidth - EDGE)
      const bottom = Math.min(rect.bottom + PAD, window.innerHeight - EDGE)
      const shown = target.isConnected && right - left > PAD && bottom - top > PAD
      element.style.transform = `translate(${left}px, ${top}px)`
      element.style.width = `${Math.max(0, right - left)}px`
      element.style.height = `${Math.max(0, bottom - top)}px`
      element.style.opacity = shown ? '1' : '0'
      frame = window.requestAnimationFrame(follow)
    }
    follow()
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearTimeout(settle)
    }
  }, [target])

  useEffect(() => {
    const element = ring.current
    if (!element || press === 0) return
    element.setAttribute('data-press', '')
    const off = window.setTimeout(() => element.removeAttribute('data-press'), PRESS_MS)
    return () => window.clearTimeout(off)
  }, [press])

  return createPortal(
    <div
      ref={ring}
      aria-hidden
      data-testid="demo-ring"
      style={{ opacity: 0 }}
      className="pointer-events-none fixed top-0 left-0 z-60 rounded-lg border-2 border-primary shadow-[0_0_0_4px_color-mix(in_oklch,var(--primary)_22%,transparent)] data-press:bg-primary/10"
    />,
    document.body,
  )
}
