// 첫 화면 흐름 장면(DESIGN.md 12절): 흐름 띠 + 실제 3D 배치 그림 위에서 단계가 바뀌는 판.
// - 넓은 화면(769px 이상): 판이 위 막대 아래에 붙고(sticky), 스크롤 진행에 따라 다섯 단계 — 배 전체 → No.3 화물창 확대 →
//   B31P · L31C 이름표와 물결 고리 → 판단 요약 숫자(총변경비용 · 추가 공수 · 추가 재료비 · 결정 기한, 0부터 올라감) → 결재·A4 검토서 카드가
//   옆에서 들어옴. 흐름 띠는 지금 단계 칸을 강조한다(번호 배지 없음). 스크롤은 관찰기로 장면이 보일 때만 듣고 requestAnimationFrame
//   으로 한 번에 한 번만 잰다 — 바뀌는 것은 단계 값(다섯 번)뿐이고 움직임은 CSS transform·opacity 전환(합성 단계만, 레이아웃 그대로).
//   마우스를 쓰는 기기에서는 판이 마우스 쪽으로 아주 조금 기운다.
// - 움직임 줄이기: 붙지 않고 마지막 단계 한 장(확대 · 이름표 · 숫자 · 검토서, 물결 고리 없음).
// - 좁은 화면(768px 이하): 붙지 않고 3D 배치 · 판단 요약 숫자 · 검토서 카드가 차례로 나타나는 판(이름표는 그림 밖 머리 줄).
// three.js는 쓰지 않는다(첫 화면 무게) — 실제 화면을 찍은 그림(ship-whole, 1배·2배 webp)을 확대·이동한다.
import { type CSSProperties, type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { REPORT_HEAD_SHOT, REPORT_SIGN_SHOT, SHIP_WHOLE_SHOT } from './captures'
import { FLOW, type FlowKey } from './content'
import { SHOWCASE_TODAY, changeText, costText, verdictText } from './example'
import { SCENE_STEPS, SHIP_POINTS, STEP_FLOW, sceneFlags, stageAt, zoomTransform, zoomed } from './sceneSteps'
import { mediaStore } from './media'
import { prefersReducedMotion, useCountUp, useInView } from './motion'
import { Reveal, Rise } from './Reveal'
import { ShotImage } from './Shot'

const CHANGE = changeText(SHOWCASE_TODAY)
const COST = costText(SHOWCASE_TODAY)
const VERDICT = verdictText(SHOWCASE_TODAY)
const BLOCKS = SHOWCASE_TODAY.nodes.filter((n) => n.entity_type === 'block').length

/** 흐름 띠의 값 줄(모두 example.json 값 — 결재선 이름만 제품 설정). */
const FLOW_VALUE: Record<FlowKey, string> = {
  change: CHANGE.action,
  scope: `영향 ${SHOWCASE_TODAY.impact_count}건 · 블록 ${BLOCKS}개`,
  cost: `${COST.total} · ${COST.hours} · ${COST.material}`,
  deadline: VERDICT.dDay && VERDICT.deadline ? `${VERDICT.dDay} · ${VERDICT.deadline}` : '결정 기한',
  approval: '파트장 → 팀장 → 본부장',
}

/** 넓은 화면(붙는 장면) — 768px 이하는 단순한 판. CSS 쿼리와 같은 값으로 가른다(media.ts). */
const WIDE = mediaStore('(min-width: 48.0625rem)')
function useWide(): boolean {
  return useSyncExternalStore(WIDE.subscribe, WIDE.getSnapshot, () => false)
}

/** 흐름 띠: 제목 · 예시 값 · 칸 사이 화살표. active 칸은 옅은 primary 바탕과 밑줄(번호 없음). */
function FlowRail({ active = [] }: { active?: readonly FlowKey[] }) {
  return (
    <ol aria-label="설계변경 한 건의 처리 흐름" className="rp-flow grid gap-2 sm:grid-cols-5 sm:gap-3">
      {FLOW.map((step) => {
        const on = active.includes(step.key)
        return (
          <li key={step.key} className="rp-flow-step min-w-0" data-active={on ? 'true' : 'false'}>
            <a
              href={step.href}
              aria-current={on ? 'step' : undefined}
              className="rp-flow-link block h-full rounded-[14px] px-3 py-3 text-left hover:bg-muted lg:px-4"
            >
              <span className="rp-flow-title block text-md font-bold tracking-tight text-foreground lg:text-lg">{step.title}</span>
              <span className="mt-0.5 block text-sm text-foreground-secondary tabular-nums">{FLOW_VALUE[step.key]}</span>
            </a>
          </li>
        )
      })}
    </ol>
  )
}

/** 판 머리: 설계변경(업무 화면 상세 머리와 같은 값) + '실제 업무 화면'. */
function StageHead() {
  return (
    <figcaption className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 pb-3 sm:pb-4">
      <span className="font-mono text-sm">{SHOWCASE_TODAY.ecn_id}</span>
      <span className="min-w-0 text-md font-semibold">{SHOWCASE_TODAY.title}</span>
      <span className="w-full text-sm text-foreground-secondary sm:ml-auto sm:w-auto">실제 업무 화면</span>
    </figcaption>
  )
}

function Stat({ label, shown, final, sub, tone = '' }: { label: string; shown: string; final: string; sub?: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-foreground-secondary">{label}</dt>
      <dd className={`text-key leading-tight font-semibold whitespace-nowrap tabular-nums ${tone}`}>
        <span aria-hidden className="rp-count" data-final={final}>
          <span>{shown}</span>
        </span>
        <span className="sr-only">{final}</span>
      </dd>
      {sub && <dd className="mt-0.5 text-xs text-foreground-secondary">{sub}</dd>}
    </div>
  )
}

/**
 * 판단 요약 숫자(업무 화면 판단 요약과 같은 값·순서 — 총변경비용 → 추가 공수 → 추가 재료비, 그다음 결정 기한). run이 켜지면
 * 0부터 올라간다. row = 넓은 장면의 위쪽 띠(네 칸 한 줄 — 배 그림 이름표를 가리지 않게), 아니면 두 줄.
 */
function NumbersCard({ run, row = false, className = '' }: { run: boolean; row?: boolean; className?: string }) {
  const total = useCountUp(COST.total, run)
  const hours = useCountUp(COST.hours, run)
  const material = useCountUp(COST.material, run)
  const dDay = useCountUp(VERDICT.dDay ?? '', run)
  return (
    <div className={`rp-float rounded-[14px] border border-border bg-surface p-3.5 sm:p-4 ${className}`}>
      <p className="text-xs font-semibold text-foreground-secondary">판단 요약 · 결정 기한</p>
      <dl className={`mt-2 grid gap-x-4 gap-y-3 ${row ? 'grid-cols-4' : 'grid-cols-2'}`}>
        <Stat label="총변경비용" shown={total} final={COST.total} />
        <Stat label="추가 공수" shown={hours} final={COST.hours} sub={`≈ ${COST.laborMoney}`} />
        <Stat
          label="추가 재료비"
          shown={material}
          final={COST.material}
          sub={COST.ordered ? `이미 발주 ${COST.ordered}건` : undefined}
        />
        <Stat label="결정 기한" shown={dDay} final={VERDICT.dDay ?? ''} sub={VERDICT.deadline ?? ''} tone="text-warning" />
      </dl>
    </div>
  )
}

/** 결재·A4 검토서 카드: 검토서 머리(제목·ECN 줄)와 결재란(담당·파트장·팀장·본부장)만 크게 — A4 전체 축소판은 글이 읽히지 않는다. */
function ReportCard({ sizes }: { sizes: string }) {
  return (
    <div className="rp-float overflow-hidden rounded-[14px] border border-border bg-surface">
      <p className="border-b border-border px-4 py-2 text-xs font-semibold text-foreground-secondary sm:text-sm">결재·A4 검토서</p>
      <div className="px-2 pt-2 pb-1">
        <ShotImage shot={REPORT_HEAD_SHOT} sizes={sizes} />
        <ShotImage shot={REPORT_SIGN_SHOT} sizes={sizes} className="mt-1" />
      </div>
    </div>
  )
}

const pct = (value: number) => `${(value * 100).toFixed(2)}%`
const B31P = zoomed(SHIP_POINTS.b31p)
const L31C = zoomed(SHIP_POINTS.l31c)
const WAVE = zoomed(SHIP_POINTS.wave)

/** 마우스 쪽으로 아주 조금 기우는 판(마우스를 쓰는 기기 · 움직임 줄이기 아님). CSS 변수만 바꾼다. */
function useTilt(enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = ref.current
    if (!element || !enabled || !window.matchMedia?.('(hover: hover) and (pointer: fine)').matches) return
    let frame = 0
    let next = { x: 0, y: 0 }
    const apply = () => {
      frame = 0
      element.style.setProperty('--tilt-x', next.x.toFixed(3))
      element.style.setProperty('--tilt-y', next.y.toFixed(3))
    }
    const move = (event: PointerEvent) => {
      const box = element.getBoundingClientRect()
      next = { x: ((event.clientX - box.left) / box.width - 0.5) * 2, y: ((event.clientY - box.top) / box.height - 0.5) * 2 }
      if (!frame) frame = requestAnimationFrame(apply)
    }
    const leave = () => {
      next = { x: 0, y: 0 }
      if (!frame) frame = requestAnimationFrame(apply)
    }
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerleave', leave)
    return () => {
      cancelAnimationFrame(frame)
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerleave', leave)
    }
  }, [enabled])
  return ref
}

/** 3D 배치 그림 위 장면(넓은 화면). step = 지금 단계(0~4). */
function SceneFrame({ step, still }: { step: number; still: boolean }) {
  const flags = sceneFlags(step)
  const tilt = useTilt(!still)
  const on = (value: boolean) => (value ? 'on' : 'off')
  return (
    <div ref={tilt} className="rp-scene-tilt">
      <div
        className="rp-scene rp-card relative overflow-hidden rounded-[20px] border border-border bg-surface lg:rounded-[28px]"
        data-zoom={on(flags.zoom)}
        data-blocks={on(flags.blocks)}
        data-numbers={on(flags.numbers)}
        data-report={on(flags.report)}
        data-still={still ? 'true' : 'false'}
        style={{ '--zoom': zoomTransform() } as CSSProperties}
      >
        <div className="rp-scene-zoom">
          <ShotImage shot={SHIP_WHOLE_SHOT} sizes="180vw" eager />
        </div>
        {/* 물결 고리: 두 영향 블록 덩어리에서 퍼진다(확대 뒤 자리) */}
        <div aria-hidden className="rp-scene-waves pointer-events-none absolute" style={{ left: pct(WAVE.x), top: pct(WAVE.y) }}>
          <span className="rp-scene-wave" />
          <span className="rp-scene-wave" style={{ '--d': '1.2s' } as CSSProperties} />
        </div>
        <div className="rp-scene-pin-label absolute" style={{ left: pct(B31P.x), top: pct(B31P.y + 0.06) }}>
          <span className="rp-scene-label rp-scene-label-below">B31P · 바꾸는 판 3장 · 영향 높음</span>
        </div>
        {/* 그림 속 이름표(L31C · 높음 · 1차) 바로 아래 — 왼쪽에 두면 확대 뒤 판 밖으로 나간다 */}
        <div className="rp-scene-pin-label absolute" style={{ left: pct(L31C.x), top: pct(L31C.y + 0.06) }}>
          <span className="rp-scene-label rp-scene-label-below" style={{ '--d': '0.35s' } as CSSProperties}>
            L31C · 맞대기 용접 이웃 블록
          </span>
        </div>
        <span className="rp-scene-tag absolute top-3 left-4 rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-semibold text-foreground-secondary">
          영향 범위 · 3D 배치 {flags.zoom ? 'No.3 화물창' : '전체 시점'}
        </span>
        {/* 4단계: 위쪽 띠(네 칸 한 줄, 불투명) — 배 그림의 B31P·L31C·S31P 이름표보다 위 */}
        <div className="rp-scene-numbers absolute top-[3%] right-[2.5%] left-[2.5%]">
          <NumbersCard run={flags.numbers} row />
        </div>
        {/* 5단계: 뒤 장면(배 그림·이름표·숫자 띠)을 흰 반투명 덮개 + 약한 흐림으로 가리고 */}
        <div aria-hidden className="rp-scene-veil pointer-events-none absolute inset-0" />
        {/* 판 가운데에 검토서 머리 + 결재란을 크게(판 폭 64%, 최대 1000px — 1440에서 약 880px, 결재란 이름 18px 이상) */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="rp-scene-report w-[64%] max-w-[1000px]">
            <ReportCard sizes="(min-width: 1560px) 1000px, 64vw" />
          </div>
        </div>
      </div>
    </div>
  )
}

/** 붙어 있는 장면의 지금 단계: 장면이 보일 때만 스크롤을 듣고, 한 장면에 한 번(requestAnimationFrame) 잰다. */
function useSceneStep(): [React.RefObject<HTMLDivElement | null>, number] {
  const track = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState(0)
  useEffect(() => {
    const element = track.current
    if (!element) return
    let frame = 0
    const measure = () => {
      frame = 0
      const box = element.getBoundingClientRect()
      const pin = parseFloat(getComputedStyle(element).getPropertyValue('--pin')) || 64
      setStep(stageAt(box.top, box.height, window.innerHeight, pin))
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    let listening = false
    const listen = (yes: boolean) => {
      if (yes === listening) return
      listening = yes
      if (yes) {
        window.addEventListener('scroll', onScroll, { passive: true })
        window.addEventListener('resize', onScroll)
        onScroll()
      } else {
        window.removeEventListener('scroll', onScroll)
        window.removeEventListener('resize', onScroll)
      }
    }
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(([entry]) => listen(entry.isIntersecting))
    if (observer) observer.observe(element)
    else listen(true)
    return () => {
      observer?.disconnect()
      listen(false)
      cancelAnimationFrame(frame)
    }
  }, [])
  return [track, step]
}

function WideScene() {
  const [track, step] = useSceneStep()
  const name = SCENE_STEPS[step]
  return (
    <div ref={track} className="rp-scene-track mt-14 lg:mt-20" data-step={name}>
      <div className="rp-scene-pin">
        <Rise delay={320}>
          <FlowRail active={STEP_FLOW[name]} />
        </Rise>
        <Rise delay={400} className="rp-scene-fit mt-3 lg:mt-4">
          <figure className="rp-stage">
            <StageHead />
            <SceneFrame step={step} still={false} />
          </figure>
        </Rise>
      </div>
    </div>
  )
}

/** 움직임 줄이기(넓은 화면): 마지막 단계 한 장. */
function StillScene() {
  return (
    <div className="mt-14 lg:mt-20">
      <FlowRail />
      <figure className="rp-stage rp-scene-fit mt-4">
        <StageHead />
        <SceneFrame step={SCENE_STEPS.length - 1} still />
      </figure>
    </div>
  )
}

function NarrowPiece({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rp-card overflow-hidden rounded-[14px] border border-border bg-surface">
      <p className="border-b border-border px-4 py-2 text-xs font-semibold text-foreground-secondary">{label}</p>
      {children}
    </div>
  )
}

/** 좁은 화면: 붙지 않고 차례로 나타나는 판(숫자는 화면에 들어오면 0부터). 이름표는 그림 밖 머리 줄. */
function NarrowScene() {
  const [ref, seen] = useInView<HTMLDivElement>()
  return (
    <div className="mt-12">
      <FlowRail />
      <figure className="rp-stage mt-4 rounded-[24px] border border-border bg-canvas p-3 sm:p-5">
        <StageHead />
        <div className="grid gap-4">
          <Reveal>
            <NarrowPiece label="영향 범위 · 3D 배치 전체 시점">
              <ShotImage shot={SHIP_WHOLE_SHOT} sizes="calc(100vw - 56px)" eager />
            </NarrowPiece>
          </Reveal>
          <div ref={ref}>
            <Reveal delay={80}>
              <NumbersCard run={seen} />
            </Reveal>
          </div>
          <Reveal delay={160}>
            <ReportCard sizes="calc(100vw - 72px)" />
          </Reveal>
        </div>
      </figure>
    </div>
  )
}

export function HeroScene() {
  const wide = useWide()
  if (!wide) return <NarrowScene />
  return prefersReducedMotion() ? <StillScene /> : <WideScene />
}
