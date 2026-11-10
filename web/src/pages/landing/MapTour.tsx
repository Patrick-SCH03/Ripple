// 영향 지도 둘러보기(#map, DESIGN.md 12절): 실제 영향 지도 그림을 화면에 고정하고, 옆 단계(바뀐 판 → 용접한 판 → 블록
// 재작업 → 이웃 블록 → 도면 개정 → 발주 → 탑재 일정)를 넘길 때마다 그 카드들을 확대하고 테두리로 강조한다(나머지는 흐림).
// 넓은 화면(CSS lg 이상 — 글꼴 16px이면 1024px)은 글 | 고정 그림, 좁은 화면은 단계마다 글 → 그 단계로 확대한 그림 — 폭에
// 맞는 한쪽만 그린다(제목이 두 벌 생기지 않게). 폭은 CSS와 같은 미디어 쿼리로 가른다(media.ts — 창 폭 숫자로 따로 재면
// 확대·글꼴 크기 설정에서 어긋난다). 고정 그림 상자는 보이는 높이 안에 다 들어오게 폭을 줄인다(.rp-pin, landing.css).
// 단계 문구는 example.json, 카드 자리는 captures.ts. 움직임 줄이기면 확대가 바로 바뀐다(landing.css).
import type { CSSProperties } from 'react'
import { MAP_SHOT, largestUrl, mapFocus } from './captures'
import { SHOWCASE_TODAY } from './example'
import { mapSteps, type MapStep } from './mapSteps'
import { useLg } from './media'
import { useActiveStep } from './motion'
import { focusView, type Fraction, type View } from './zoom'

const STEPS = mapSteps(SHOWCASE_TODAY)

/** 보는 상자(가로/세로 비율)와 단계마다의 확대: 넓은 화면은 16:10, 휴대폰은 더 높은 4:3에 더 크게(카드 글자가 보이게). */
interface Look {
  box: number
  overview: View
  views: View[]
}

function look(box: number, maxZoom: number): Look {
  return {
    box,
    overview: focusView(MAP_SHOT, box, null),
    views: STEPS.map((step) => focusView(MAP_SHOT, box, mapFocus(step.key), { maxZoom })),
  }
}

const WIDE_LOOK = look(16 / 10, 3.2)
const PHONE_LOOK = look(4 / 3, 4.5)

const pct = (f: Fraction): CSSProperties => ({
  left: `${f.left * 100}%`,
  top: `${f.top * 100}%`,
  width: `${f.width * 100}%`,
  height: `${f.height * 100}%`,
})

/** 단계마다 하나씩 겹쳐 둔 강조 테두리(지금 단계만 보인다). only면 그 단계 것만. */
function FocusRings({ views, active, only }: { views: View[]; active: number | null; only?: number }) {
  return views.map((v, i) =>
    v.focus && (only === undefined || only === i) ? (
      <span
        key={STEPS[i].key}
        aria-hidden
        className="rp-focus absolute"
        data-on={active === i ? 'true' : 'false'}
        style={{ ...pct(v.focus), ['--s' as string]: v.scale }}
      />
    ) : null,
  )
}

function ViewerCaption({ active }: { active: number | null }) {
  const step = active === null ? null : STEPS[active]
  return (
    <figcaption className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm text-foreground-secondary">
      <span className="min-w-0 truncate">
        {step ? (
          <>
            <span className="font-semibold text-foreground tabular-nums">
              {(active ?? 0) + 1} / {STEPS.length}
            </span>{' '}
            {step.title}
          </>
        ) : (
          '영향 지도 전체'
        )}
      </span>
      <span className="shrink-0 text-xs">실제 화면</span>
    </figcaption>
  )
}

/**
 * 고정 그림: active 단계로 확대(없으면 전체). 확대해서 보므로 늘 가장 큰 배율(3배) 그림(작은 그림을 키우면 흐리다).
 * 고정(.rp-pin)일 때는 상자 폭을 보이는 높이로도 묶는다(--rp-box = 가로/세로) — 키 작은 창에서 캡션·아래가 잘리지 않게.
 */
function Viewer({ active, only, at = WIDE_LOOK }: { active: number | null; only?: number; at?: Look }) {
  const view = active === null ? at.overview : at.views[active]
  return (
    <figure
      className="rp-card rp-viewer overflow-hidden rounded-[18px] border border-border bg-surface"
      style={{ ['--rp-box' as string]: at.box }}
    >
      <div className="relative overflow-hidden bg-surface" style={{ aspectRatio: `${at.box}` }}>
        <div
          className="rp-zoom absolute inset-0 origin-top-left"
          style={{ transform: `translate(${view.x * 100}%, ${view.y * 100}%) scale(${view.scale})` }}
        >
          <img
            src={largestUrl(MAP_SHOT)}
            width={MAP_SHOT.width}
            height={MAP_SHOT.height}
            alt={only === undefined || only === 0 ? MAP_SHOT.alt : ''}
            loading="lazy"
            decoding="async"
            className="absolute max-w-none"
            style={pct(at.overview.image)}
          />
          <FocusRings views={at.views} active={active} only={only} />
        </div>
      </div>
      <ViewerCaption active={active} />
    </figure>
  )
}

/** 단계 글(번호 배지 없이 왼쪽 세로 막대 — 지금 단계는 primary). 지금이 아닌 단계는 흐린 글색으로 낮춘다(투명도로 흐리지 않음 — 글자 대비 4.5:1 유지). */
function StepText({ step, dim = false }: { step: MapStep; dim?: boolean }) {
  return (
    <div className="flex gap-4">
      <span aria-hidden className={`w-1 shrink-0 rounded-full transition-colors duration-500 ${dim ? 'bg-border' : 'bg-primary'}`} />
      <div className="min-w-0 py-0.5">
        <h3
          className={`text-item font-bold tracking-tight transition-colors duration-500 lg:text-subhead ${dim ? 'text-muted-foreground' : 'text-foreground'}`}
        >
          {step.title}
        </h3>
        <p className={`mt-1.5 text-lead text-pretty transition-colors duration-500 ${dim ? 'text-muted-foreground' : 'text-foreground-secondary'}`}>
          {step.body}
        </p>
      </div>
    </div>
  )
}

/** 넓은 화면: 왼쪽 단계 글이 화면 가운데를 지날 때마다 오른쪽 고정 그림이 그 단계로 확대된다. */
function WideTour() {
  const [ref, active] = useActiveStep()
  return (
    <div className="grid grid-cols-[minmax(0,4fr)_minmax(0,7fr)] gap-14">
      <ol ref={ref} className="py-[22vh]">
        {STEPS.map((step, i) => (
          <li key={step.key} data-step={i} className="flex min-h-[44vh] items-center" aria-current={active === i ? 'step' : undefined}>
            <StepText step={step} dim={active !== null && active !== i} />
          </li>
        ))}
      </ol>
      <div>
        <div className="rp-pin">
          <Viewer active={active} />
        </div>
      </div>
    </div>
  )
}

/** 좁은 화면: 단계마다 글 → 그 단계로 확대한 그림. */
function StackedTour() {
  return (
    <ol className="flex flex-col gap-14">
      {STEPS.map((step, i) => (
        <li key={step.key} className="flex flex-col gap-5">
          <StepText step={step} />
          <Viewer active={i} only={i} at={PHONE_LOOK} />
        </li>
      ))}
    </ol>
  )
}

export function MapTour() {
  return useLg() ? <WideTour /> : <StackedTour />
}
