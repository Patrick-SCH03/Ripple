// 시연 실행 상태: 시작 · 멈추기 · 안내 띠 문구 · 강조할 요소. 실행 중에 사람이 다른 곳을 누르거나(띠 밖) 키를 누르거나
// 휠을 굴리면 깔끔하게 끝낸다(Esc = 멈추기). 화면이 사라지면(다른 경로·지도 바뀜·좁은 화면) 함께 끝난다.
// 사람의 조작은 isTrusted로 가른다 — 실행기가 보내는 누름·입력은 스크립트 이벤트라 멈추지 않는다.
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { DONE_MS, STUCK_MS, countedSteps, stopsOnKey, type DemoPhase } from '@/lib/demo'
import type { DemoScenario } from '@/lib/demoScenarios'
import { DemoAborted, listen } from './demoDom'
import { runScenario } from './runScenario'

export interface DemoState {
  phase: DemoPhase
  scenarioId: string | null
  n: number
  total: number
  caption: string
  /** 강조할 요소와, 누를 때마다 늘어나는 번호(테두리를 한 번 깜빡인다). */
  spot: Element | null
  press: number
}

const IDLE: DemoState = { phase: 'idle', scenarioId: null, n: 0, total: 0, caption: '', spot: null, press: 0 }

export interface DemoRunner {
  state: DemoState
  start: (scenario: DemoScenario) => void
  stop: () => void
  /** 안내 띠(이 안의 누름은 멈춤으로 치지 않는다 — 띠의 단추가 따로 처리). */
  bandRef: RefObject<HTMLDivElement | null>
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

export function useDemoRunner(): DemoRunner {
  const [state, setState] = useState<DemoState>(IDLE)
  const controller = useRef<AbortController | null>(null)
  const linger = useRef<number | undefined>(undefined)
  const bandRef = useRef<HTMLDivElement | null>(null)

  const stop = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    window.clearTimeout(linger.current)
    setState(IDLE)
  }, [])

  const start = useCallback(
    (scenario: DemoScenario) => {
      controller.current?.abort()
      window.clearTimeout(linger.current)
      const run = new AbortController()
      controller.current = run
      // 첫 단계 문구가 뜨기 전(준비 단계 동안)에는 번호 없이 시나리오 이름을 띄운다(n = 0)
      const total = countedSteps(scenario.steps)
      setState({ ...IDLE, phase: 'running', scenarioId: scenario.id, n: 0, total, caption: scenario.name })
      const view = {
        step: (n: number, all: number, caption: string) => {
          if (!run.signal.aborted) setState((s) => ({ ...s, n, total: all, caption }))
        },
        spot: (element: Element | null, pressed = false) => {
          if (!run.signal.aborted) setState((s) => ({ ...s, spot: element, press: pressed ? s.press + 1 : s.press }))
        },
      }
      // 끝나거나 막히면 띠를 잠깐 남겨 두고 닫는다(강조는 바로 지운다)
      const settle = (phase: 'done' | 'stuck') => {
        if (run.signal.aborted) return
        controller.current = null
        setState((s) => ({ ...s, phase, spot: null }))
        linger.current = window.setTimeout(() => setState(IDLE), phase === 'done' ? DONE_MS : STUCK_MS)
      }
      runScenario(scenario, view, run.signal, prefersReducedMotion()).then(
        () => settle('done'),
        (error: unknown) => {
          if (error instanceof DemoAborted || run.signal.aborted) return
          console.warn('시연 멈춤', error)
          settle('stuck')
        },
      )
    },
    [],
  )

  // 실행 중 사람의 조작 → 끝내기. 띠 안의 누름은 띠 단추가 처리한다(누름에서 띠를 없애면 놓을 때 아래 요소가 눌린다)
  const running = state.phase === 'running'
  const showing = state.phase !== 'idle'
  useEffect(() => {
    if (!showing) return
    const inBand = (target: EventTarget | null) => target instanceof Node && Boolean(bandRef.current?.contains(target))
    const onPointer = (event: Event) => {
      if (event.isTrusted && running && !inBand(event.target)) stop()
    }
    const onKey = (event: KeyboardEvent) => {
      if (!event.isTrusted) return
      if (event.key === 'Escape') {
        event.preventDefault()
        stop()
      } else if (running && stopsOnKey(event.key)) stop()
    }
    const passive = { capture: true, passive: true }
    const offs = [
      listen('pointerdown', onPointer, true),
      listen('wheel', onPointer, passive),
      listen('touchstart', onPointer, passive),
      listen('keydown', onKey, true),
      listen('popstate', stop),
    ]
    return () => offs.forEach((off) => off())
  }, [showing, running, stop])

  // 화면이 사라지면(경로 이동·지도 바뀜·좁은 화면) 실행을 끊는다
  useEffect(
    () => () => {
      controller.current?.abort()
      window.clearTimeout(linger.current)
    },
    [],
  )

  return { state, start, stop, bandRef }
}
