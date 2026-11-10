// 상세의 구역 카드(DESIGN.md 2절): 판단 요약 · 영향 범위 · 할 일 · 근거 상세를 경계가 또렷한 카드로 나눈다.
// 머리 = 옅은 띠(bg.muted) + 제목(구역 이동 막대와 같은 이름, 22px) + 오른쪽 보조(건수·ⓘ), 아래 구분선. 무엇이 들었는지 적는
// 설명 줄은 두지 않는다(제목과 소제목으로 충분 — 보조 한 줄 원칙). 카드 테두리는 border.strong(바탕과 대비), 그림자 없음.
// 카드 안 소구역은 SubSection(소제목 + 위 구분선 + 같은 위 여백)으로 같은 규칙을 쓴다.
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  id: string
  title: string
  /** 머리 오른쪽: 건수·ⓘ 같은 짧은 보조. */
  aside?: ReactNode
  className?: string
  children: ReactNode
}

export function DetailSection({ id, title, aside, className, children }: Props) {
  const titleId = `${id}-title`
  return (
    <section
      id={id}
      aria-labelledby={titleId}
      data-detail-section
      // 구역 이동 막대(고정, 약 48px)에 머리가 가리지 않게
      className={cn('scroll-mt-14 rounded-md border border-border-strong bg-surface', className)}
    >
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-t-md border-b border-border-strong bg-muted px-4 py-2">
        {/* 구역 이동 막대가 누르면 여기로 초점(읽기 프로그램이 구역 이름부터 읽게) */}
        <h3 id={titleId} tabIndex={-1} className="text-lg font-semibold outline-none">
          {title}
        </h3>
        {aside && <div className="flex items-center gap-1 text-sm text-foreground-secondary">{aside}</div>}
      </header>
      <div className="space-y-4 p-3 sm:p-4">{children}</div>
    </section>
  )
}

interface SubProps {
  /** 소제목 h4의 id(aria-labelledby 연결). */
  id: string
  title: ReactNode
  /** 소제목 바로 옆(ⓘ·건수 칩). */
  info?: ReactNode
  /** 머리 오른쪽(펼치기 단추 등). */
  action?: ReactNode
  /** 구역 카드 안 첫 소구역이면 위 구분선을 뺀다. */
  first?: boolean
  className?: string
  testId?: string
  children?: ReactNode
}

/** 구역 카드 안 소구역: 소제목(18px semibold) + 위 구분선 + 같은 위 여백(12px) — 조치·현장 상태·사전 점검·중량 변화·일정 묶음이 같은 모양. */
export function SubSection({ id, title, info, action, first = false, className, testId, children }: SubProps) {
  return (
    <section
      aria-labelledby={id}
      className={cn(!first && 'border-t border-border pt-3', className)}
      data-testid={testId}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
          <h4 id={id} className="text-md font-semibold">
            {title}
          </h4>
          {info}
        </div>
        {action}
      </div>
      {children !== undefined && <div className="mt-2">{children}</div>}
    </section>
  )
}
