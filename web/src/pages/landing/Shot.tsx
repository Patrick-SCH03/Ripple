// 실제 업무 화면 그림 한 장(DESIGN.md 12절): 1배·2배 webp(srcset)와 그림 위 강조 테두리(번호 없음). 강조 자리는
// captures.ts의 사각형(그림 CSS 픽셀)을 그림 크기 비율(%)로 옮겨 그려 어느 폭에서도 같은 곳을 가리킨다.
// frame: 'panel' = 화면 조각 이름('실제 화면 · 합성 데이터')이 붙은 둥근 판, 'none' = 틀 없이.
import type { CSSProperties, ReactNode } from 'react'
import { percentBox, shotUrl, srcSet, type Capture, type Rect } from './captures'

export interface Mark {
  rect: Rect
  className?: string
  style?: CSSProperties
}

export function ShotImage({
  shot,
  sizes,
  eager = false,
  className,
}: {
  shot: Capture
  sizes: string
  eager?: boolean
  className?: string
}) {
  return (
    <img
      src={shotUrl(shot)}
      srcSet={srcSet(shot)}
      sizes={sizes}
      width={shot.width}
      height={shot.height}
      alt={shot.alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      fetchPriority={eager ? 'high' : 'auto'}
      className={`block h-auto w-full ${className ?? ''}`}
    />
  )
}

export function Marks({ shot, marks }: { shot: Capture; marks: Mark[] }) {
  return (
    <>
      {marks.map((mark, i) => (
        <span
          key={i}
          aria-hidden
          className={`rp-mark pointer-events-none absolute ${mark.className ?? ''}`}
          style={{ ...percentBox(shot, mark.rect), ...mark.style }}
        />
      ))}
    </>
  )
}

export function Shot({
  shot,
  sizes,
  frame = 'panel',
  title,
  marks = [],
  eager = false,
  className,
  bodyClassName,
  imageClassName,
  children,
}: {
  shot: Capture
  sizes: string
  frame?: 'panel' | 'none'
  /** 판 머리의 화면 조각 이름('panel' 틀). */
  title?: string
  marks?: Mark[]
  eager?: boolean
  className?: string
  /** 그림 + 강조 묶음(같이 확대할 때). */
  bodyClassName?: string
  imageClassName?: string
  /** 그림 위에 더 얹을 것(같은 좌표계). */
  children?: ReactNode
}) {
  const body = (
    <div className={`relative ${bodyClassName ?? ''}`}>
      <ShotImage shot={shot} sizes={sizes} eager={eager} className={imageClassName} />
      <Marks shot={shot} marks={marks} />
      {children}
    </div>
  )
  if (frame === 'none') return <div className={className}>{body}</div>
  return (
    <div className={`rp-card overflow-hidden rounded-[16px] border border-border bg-surface ${className ?? ''}`}>
      {title && (
        <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-border px-4 py-2.5 text-sm sm:px-5">
          <span className="font-semibold text-foreground-secondary">{title}</span>
          <span className="text-xs text-foreground-secondary">실제 화면 · 합성 데이터</span>
        </p>
      )}
      <div className="p-3 sm:p-5">{body}</div>
    </div>
  )
}
