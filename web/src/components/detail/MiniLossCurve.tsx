// 결정 기한 카드 안의 작은 추가손실 곡선(DESIGN.md 6절): '하루 늦으면 +금액'과 기준일 → 결정 기한(점선) → 다음 날 계단.
// 곡선 탭과 같은 데이터(lib/miniCurve)이고, 누르면 추가손실 곡선 탭을 연다.
import { ChevronRight } from 'lucide-react'
import type { AnalysisResult } from '@/api/client'
import { formatDay, formatShortDay } from '@/lib/format'
import { miniCurve, stepPath, xPercent } from '@/lib/miniCurve'

const W = 200
const H = 36

/** 마감일 이름표를 마감일 자리 왼쪽에 붙일 수 있는 최소 자리(%) — 더 왼쪽이면 기준일 이름표 대신 왼쪽 끝에. */
const ROOM = 42
/** 오른쪽 끝 '곡선 보기'와 마감일 이름표가 겹치지 않는 마감일 자리 상한(%). */
const LINK_ROOM = 70

export function MiniLossCurve({ result, onOpen }: { result: AnalysisResult; onOpen: () => void }) {
  const mini = miniCurve(result.timing.curve, result.timing.deadline)
  if (!mini) return null
  const deadlineDay = mini.points[mini.deadlineAt].day
  const today = mini.deadlineAt === 0
  const at = xPercent(mini, mini.deadlineAt)
  const lineX = (at / 100) * W
  const roomy = !today && at >= ROOM
  const deadlineLabel = today ? '오늘까지' : `기한 ${formatShortDay(deadlineDay)}`
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="mini-curve"
      aria-label={`추가손실 곡선 탭 열기 — ${today ? '오늘' : formatDay(deadlineDay)}까지 추가손실 0원 · 하루 늦으면 ${mini.rise}`}
      className="@container mt-2 block w-full rounded-sm border border-border px-2.5 pt-1.5 pb-1 text-left hover:bg-hover"
    >
      <span className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
        <span className="whitespace-nowrap text-foreground-secondary">하루 늦으면</span>
        <span className="font-semibold whitespace-nowrap text-warning tabular-nums">{mini.rise}</span>
      </span>
      <svg aria-hidden viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="mt-1 block h-9 w-full overflow-visible">
        <line x1={0} x2={W} y1={H - 4} y2={H - 4} className="stroke-border" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <line
          x1={lineX}
          x2={lineX}
          y1={0}
          y2={H}
          className="stroke-danger"
          strokeWidth={1.5}
          strokeDasharray="3 3"
          vectorEffect="non-scaling-stroke"
        />
        <path d={stepPath(mini, W, H)} fill="none" className="stroke-primary" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      {/* 아래 이름표: 카드가 좁으면(컨테이너 폭) 기준일·'곡선 보기'를 빼고 마감일만 — 글이 겹치지 않게 */}
      <span aria-hidden className="relative mt-0.5 block h-4 text-xs whitespace-nowrap text-foreground-secondary tabular-nums">
        {roomy ? (
          <>
            <span className="absolute left-0 hidden @min-[12.5rem]:inline">{formatShortDay(mini.points[0].day)}</span>
            <span className="absolute -translate-x-full pr-1" style={{ left: `${at}%` }}>
              {deadlineLabel}
            </span>
          </>
        ) : (
          <span className="absolute left-0">{deadlineLabel}</span>
        )}
        {at <= LINK_ROOM && (
          <span className="absolute right-0 hidden items-center @min-[12.5rem]:inline-flex">
            곡선 보기
            <ChevronRight aria-hidden className="size-3" />
          </span>
        )}
      </span>
    </button>
  )
}
