// 소개 화면의 절 하나(DESIGN.md 12절): 넓은 화면은 한 화면(100svh 안팎)을 통째로 쓰는 가로 꽉 찬 구성.
// - stack: 가운데 큰 제목(+ 가치 한 줄) 아래 화면 폭 대부분을 쓰는 그림.
// - split: 1024px 이상에서 왼쪽 큰 제목 · 오른쪽 큰 그림의 가로 분할(좁으면 위아래).
// 바탕은 흰 · 옅은 회색 · 밤색을 절마다 번갈아 경계를 만든다.
import type { ReactNode } from 'react'
import type { Tone } from './content'
import { FULL, TITLE } from './layout'
import { Reveal } from './Reveal'
import { pill } from './tone'

type Background = 'surface' | 'canvas' | 'night'

const BACKGROUND: Record<Background, string> = { surface: 'bg-surface', canvas: 'bg-canvas', night: 'rp-night' }

function Head({
  id,
  eyebrow,
  tag,
  title,
  lead,
  center,
  night,
}: {
  id: string
  eyebrow?: string
  tag?: { label: string; tone: Tone }
  title: ReactNode
  lead?: ReactNode
  center: boolean
  night: boolean
}) {
  return (
    <Reveal className={center ? 'mx-auto max-w-[1080px] text-center' : 'max-w-[640px]'}>
      {tag && <span className={`mb-6 ${pill(tag.tone)}`}>{tag.label}</span>}
      {eyebrow && <p className={`mb-5 text-md font-semibold lg:text-lg ${night ? 'rp-night-accent' : 'text-primary'}`}>{eyebrow}</p>}
      <h2 id={`${id}-title`} className={TITLE}>
        {title}
      </h2>
      {lead && (
        <p
          className={`mt-6 max-w-[680px] text-lead text-pretty lg:text-lead-lg ${night ? 'rp-night-muted' : 'text-foreground-secondary'} ${
            center ? 'mx-auto' : ''
          }`}
        >
          {lead}
        </p>
      )}
    </Reveal>
  )
}

export function LandingSection({
  id,
  eyebrow,
  tag,
  title,
  lead,
  layout = 'stack',
  background = 'surface',
  children,
}: {
  id: string
  eyebrow?: string
  /** 알약 꼬리표(업무 이름)와 색. */
  tag?: { label: string; tone: Tone }
  title: ReactNode
  /** 제목 아래 가치 한 줄. */
  lead?: ReactNode
  layout?: 'stack' | 'split'
  background?: Background
  children: ReactNode
}) {
  const night = background === 'night'
  const head = <Head id={id} eyebrow={eyebrow} tag={tag} title={title} lead={lead} center={layout === 'stack'} night={night} />
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={`flex scroll-mt-14 flex-col justify-center py-24 sm:py-28 lg:min-h-[100svh] lg:py-32 ${BACKGROUND[background]}`}
    >
      <div className={FULL}>
        {layout === 'split' ? (
          <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,8fr)] lg:gap-16 xl:gap-24">
            {head}
            <div className="min-w-0">{children}</div>
          </div>
        ) : (
          <>
            <div className="mb-14 lg:mb-20">{head}</div>
            {children}
          </>
        )}
      </div>
    </section>
  )
}

/** 넓은 화면에서만 줄을 바꾼다(좁으면 글자 폭대로 고르게 — text-balance). */
export const Wide = () => <br className="hidden md:inline" />
