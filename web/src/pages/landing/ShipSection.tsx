// 3D 배치 절(#ship3d, DESIGN.md 12절): 업무 화면 3D 배치(전체 화면 · 화물창 시점)의 실제 화면. 물결 전파는 같은 화면을 녹화한
// 4초 반복 영상(소리 없음)으로 보이고, 정지 그림을 밑에 깔아 두었다가 영상이 재생되기 시작하면 위에 겹친다.
// - 영상은 절이 화면 가까이(1000px 앞) 왔을 때 붙여 미리 받아 둔다(첫 화면 무게에 넣지 않음 — 소개 화면 묶음에 three를 넣지 않는다).
// - 움직임 줄이기면 영상을 붙이지 않고 정지 그림만. 5초 넘게 반복하므로 멈춤 단추를 둔다(WCAG 2.2.2).
// - 강조 테두리는 영상·그림 모두 같은 화면 비율(16:9)이라 같은 자리.
import { Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { SHIP_MARKS, SHIP_SHOT, SHIP_VIDEO } from './captures'
import { SHIP_CHIPS } from './content'
import { prefersReducedMotion, useInView } from './motion'
import { Reveal } from './Reveal'
import { Marks, ShotImage } from './Shot'
import { ChipRow } from './WorkSections'

function ShipMedia() {
  const [ref, near] = useInView<HTMLDivElement>('1000px 0px 1000px 0px')
  const still = prefersReducedMotion()
  const video = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    const element = video.current
    if (!element || !near || still) return
    if (paused) element.pause()
    else void element.play().catch(() => setPlaying(false))
  }, [near, still, paused])

  return (
    <div ref={ref} className="relative bg-surface">
      <ShotImage shot={SHIP_SHOT} sizes="(min-width: 1680px) 1600px, calc(100vw - 48px)" />
      {near && !still && (
        <video
          ref={video}
          className={`absolute inset-0 h-full w-full transition-opacity duration-500 ${playing ? 'opacity-100' : 'opacity-0'}`}
          muted
          loop
          playsInline
          preload="auto"
          aria-label={SHIP_VIDEO.label}
          onPlaying={() => setPlaying(true)}
        >
          <source src={SHIP_VIDEO.webm} type="video/webm" />
          <source src={SHIP_VIDEO.mp4} type="video/mp4" />
        </video>
      )}
      <Marks
        shot={SHIP_SHOT}
        marks={[
          { rect: SHIP_MARKS.changed },
          { rect: SHIP_MARKS.neighbor },
          { rect: SHIP_MARKS.views },
          { rect: SHIP_MARKS.list },
        ]}
      />
      {/* 재생이 시작된 뒤에만(영상을 못 읽으면 정지 그림 그대로 · 단추 없음) */}
      {!still && playing && (
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          aria-pressed={paused}
          className="absolute right-3 bottom-3 inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-surface/95 px-3.5 text-sm font-semibold text-foreground shadow-sm hover:bg-muted"
        >
          {paused ? <Play aria-hidden className="size-4" /> : <Pause aria-hidden className="size-4" />}
          {paused ? '물결 재생' : '물결 멈춤'}
        </button>
      )}
    </div>
  )
}

export function ShipBody() {
  return (
    <>
      <Reveal className="mx-auto max-w-[1600px]">
        <figure className="rp-card overflow-hidden rounded-[20px] border border-border bg-surface">
          <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-border px-4 py-2.5 text-sm sm:px-5">
            <span className="font-semibold text-foreground-secondary">3D 배치 · 화물창 시점</span>
            <span className="text-xs text-foreground-secondary">실제 화면 · 합성 데이터</span>
          </figcaption>
          <ShipMedia />
        </figure>
      </Reveal>
      <ChipRow chips={SHIP_CHIPS} tone="primary" />
    </>
  )
}
