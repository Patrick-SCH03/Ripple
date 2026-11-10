// 상세 구역 이동 막대(DESIGN.md 2절): 스크롤해도 위에 붙어 있고, 지금 보는 구역을 표시한다(스크롤 위치로 판단).
// 누르면 그 구역 머리로 이동하고 머리에 초점을 준다. 좁은 화면에서는 가로로 밀어 보는 터치 높이 단추.
import { useEffect, useState } from 'react'
import { currentSection, type DetailNavItem } from '@/lib/detailNav'
import { cn } from '@/lib/utils'

/** 막대 아래 기준선(px): 머리가 이 선을 지나면 그 구역을 보는 중으로 친다. */
const ACTIVE_LINE = 72

interface Props {
  items: readonly DetailNavItem[]
  compact: boolean
  /** 보는 분석이 바뀌면(다른 설계변경·다시 분석) 스크롤 없이도 지금 구역을 다시 잰다. */
  resetKey: string
}

export function DetailNav({ items, compact, resetKey }: Props) {
  const [active, setActive] = useState<string | null>(items[0]?.id ?? null)
  // 구역 구성·보는 분석이 바뀔 때만 다시 건다(건수 변화는 상관없음)
  const key = `${items.map((item) => item.id).join(' ')}|${resetKey}`

  useEffect(() => {
    const ids = key.split('|')[0]!.split(' ')
    const scroller = document.getElementById(ids[0] ?? '')?.closest<HTMLElement>('[data-detail-scroll]')
    if (!scroller) return
    const update = () => {
      const base = scroller.getBoundingClientRect().top
      const tops = ids.flatMap((id) => {
        const el = document.getElementById(id)
        return el ? [{ id, top: el.getBoundingClientRect().top - base }] : []
      })
      const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4
      setActive(currentSection(tops, ACTIVE_LINE, atBottom))
    }
    update()
    scroller.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      scroller.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [key])

  const go = (id: string) => {
    const section = document.getElementById(id)
    if (!section) return
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    section.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' })
    section.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true })
  }

  return (
    <nav
      aria-label="상세 구역"
      className="sticky top-0 z-10 border-b border-border bg-surface px-2"
      data-testid="detail-nav"
    >
      <ul className="no-scrollbar -mb-px flex gap-1 overflow-x-auto">
        {items.map(({ id, label, count }) => {
          const current = active === id
          return (
            <li key={id} className="shrink-0">
              <button
                type="button"
                onClick={() => go(id)}
                aria-current={current ? 'location' : undefined}
                className={cn(
                  'flex items-center gap-1.5 border-b-2 text-sm font-medium whitespace-nowrap transition-colors',
                  // 좁은 화면은 옆 여백을 줄여 큰 글자에서도 네 구역이 한 줄에 들어오게(넘치면 가로로 밀어 봄)
                  compact ? 'h-11 px-2' : 'h-10 px-3',
                  current
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-foreground-secondary hover:text-foreground',
                )}
              >
                {label}
                {count ? (
                  <span className="rounded-sm bg-muted px-1.5 text-xs tabular-nums text-foreground-secondary">
                    {count}
                  </span>
                ) : null}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
