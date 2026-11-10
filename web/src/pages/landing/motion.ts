// 소개 화면 움직임 도우미(DESIGN.md 12절): 움직임 줄이기 설정과 '화면에 들어왔나'. 움직임 줄이기거나 관찰기를 못 쓰면
// 처음부터 '들어옴'으로 본다 — 내용이 숨은 채 남지 않게.
import { useEffect, useState } from 'react'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function canObserve(): boolean {
  return typeof window !== 'undefined' && 'IntersectionObserver' in window
}

/** 요소가 화면 아래쪽 10%를 넘어 들어오면 true(한 번 들어오면 그대로). [ref 콜백, 들어왔나]. */
export function useInView<T extends Element>(rootMargin = '0px 0px -10% 0px'): [(node: T | null) => void, boolean] {
  const [node, setNode] = useState<T | null>(null)
  const [inView, setInView] = useState(() => !canObserve() || prefersReducedMotion())
  useEffect(() => {
    if (inView || !node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true)
          observer.disconnect()
        }
      },
      { rootMargin },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [node, inView, rootMargin])
  return [setNode, inView]
}

/**
 * 영향 지도 둘러보기: 묶음 안 [data-step] 단계 가운데 화면 가운데 띠(위아래 45%를 뺀 곳)를 지나는 단계의 번호.
 * 아직 어느 단계도 지나지 않았거나 관찰기를 못 쓰면 null — 부르는 쪽은 전체 지도를 보이고 단계를 흐리지 않는다.
 * 스크롤 이벤트 대신 관찰기로만 잰다. [묶음 ref, 지금 단계].
 */
export function useActiveStep(): [(node: HTMLElement | null) => void, number | null] {
  const [node, setNode] = useState<HTMLElement | null>(null)
  const [active, setActive] = useState<number | null>(null)
  useEffect(() => {
    if (!node || !canObserve()) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(Number((entry.target as HTMLElement).dataset.step ?? 0))
        }
      },
      { rootMargin: '-45% 0px -45% 0px' },
    )
    node.querySelectorAll('[data-step]').forEach((step) => observer.observe(step))
    return () => observer.disconnect()
  }, [node])
  return [setNode, active]
}

const NUMBER = /\d[\d,]*(\.\d+)?/

/** 0부터 시작하는 모양: 글 안의 첫 숫자의 자리를 0으로(자리 수·단위는 그대로). */
export function zeroed(text: string): string {
  return text.replace(NUMBER, (m) => m.replace(/\d/g, '0'))
}

/**
 * 올라가는 도중의 글: 진행 t(0 → 1, 끝으로 갈수록 느려짐)만큼 첫 숫자를 채운다. 소수 자리와 천 단위 쉼표는 끝 값 모양
 * 그대로('1,500열'은 '1,500열'로 끝난다). 숫자가 없으면 그대로.
 */
export function countFrame(text: string, t: number): string {
  const match = NUMBER.exec(text)
  if (!match) return text
  const target = Number(match[0].replace(/,/g, ''))
  const decimals = match[1] ? match[1].length - 1 : 0
  const value = target * (1 - (1 - Math.min(1, Math.max(0, t))) ** 3)
  const digits = match[0].includes(',')
    ? value.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : value.toFixed(decimals)
  return text.slice(0, match.index) + digits + text.slice(match.index + match[0].length)
}

/**
 * 글 안의 첫 숫자를 0부터 올린다(run이 true가 되면 한 번, 0.9초). 움직임 줄이기거나 숫자가 없으면 바로 끝 값.
 * 화면 읽기 프로그램에는 끝 값을 따로 둔다(호출하는 쪽이 sr-only로).
 */
export function useCountUp(text: string, run: boolean): string {
  const [shown, setShown] = useState<string | null>(null)
  const instant = !NUMBER.test(text) || prefersReducedMotion()
  useEffect(() => {
    if (instant || !run) return
    const started = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / 900)
      setShown(countFrame(text, t))
      if (t < 1) frame = window.requestAnimationFrame(tick)
    }
    frame = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frame)
  }, [text, run, instant])
  if (instant) return text
  return shown ?? zeroed(text)
}

/** 페이지를 조금이라도 내렸나(위 막대 아래 선을 그릴지). 맨 위 표지 요소가 화면 밖으로 나가면 true. */
export function useScrolled(): [(node: HTMLElement | null) => void, boolean] {
  const [node, setNode] = useState<HTMLElement | null>(null)
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    if (!node || !canObserve()) return
    const observer = new IntersectionObserver(([entry]) => setScrolled(!entry.isIntersecting))
    observer.observe(node)
    return () => observer.disconnect()
  }, [node])
  return [setNode, scrolled]
}
