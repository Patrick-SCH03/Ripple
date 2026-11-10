// 추가손실 계단 그래프(DESIGN.md 6절 곡선 탭): 기준일 → 탐색 끝, 대표값 선 + 최소~최대 띠, 마감일 세로선.
// Recharts는 크므로 곡선 탭을 처음 열 때 불러온다(기본 내보내기 = lazy 대상).
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CurvePoint, ZeroLossDeadline } from '@/api/client'
import { formatDay, formatShortDay } from '@/lib/format'
import { formatAxis, formatMoney, formatRange } from '@/lib/money'

interface Props {
  curve: readonly CurvePoint[]
  deadline: ZeroLossDeadline
  /** 보류한 곡선(겹쳐 보기). 그 곡선 자신의 추가손실 필드를 그린다. */
  held?: { label: string; curve: readonly CurvePoint[] }
}

interface Datum {
  day: string
  value: number
  band: [number, number]
  held?: number
  events: readonly string[]
}

const AXIS = { fill: 'var(--text-secondary)', fontSize: 14 }

function CurveTooltip({ active, payload, heldLabel }: { active?: boolean; payload?: { payload: Datum }[]; heldLabel?: string }) {
  const datum = active ? payload?.[0]?.payload : undefined
  if (!datum) return null
  return (
    <div className="max-w-64 rounded-md border border-border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md">
      <p className="font-medium">{formatDay(datum.day)} 확정</p>
      <p className="tabular-nums">
        추가손실 {formatMoney(datum.value)}
        {datum.band[0] !== datum.band[1] && (
          <span className="text-foreground-secondary"> ({formatRange(datum.band[0], datum.band[1])})</span>
        )}
      </p>
      {datum.held !== undefined && heldLabel && (
        <p className="tabular-nums">
          {heldLabel}: {formatMoney(datum.held)}
        </p>
      )}
      {datum.events.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-foreground-secondary">
          {datum.events.map((event) => (
            <li key={event}>{event}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function LossCurve({ curve, deadline, held }: Props) {
  const heldByDay = new Map(held?.curve.map((point) => [point.confirm_on, point.additional_loss.value]))
  const data: Datum[] = curve.map((point) => ({
    day: point.confirm_on,
    value: point.additional_loss.value,
    band: [point.additional_loss.low, point.additional_loss.high],
    held: heldByDay.get(point.confirm_on),
    events: point.events,
  }))
  const marked = deadline.kind !== 'none_in_horizon'
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 16, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
          <XAxis
            dataKey="day"
            tickFormatter={formatShortDay}
            tick={AXIS}
            stroke="var(--border-strong)"
            minTickGap={28}
          />
          <YAxis tickFormatter={formatAxis} tick={AXIS} stroke="var(--border-strong)" width={52} />
          <Tooltip content={<CurveTooltip heldLabel={held?.label} />} />
          <Area
            dataKey="band"
            type="stepAfter"
            stroke="none"
            fill="var(--primary)"
            fillOpacity={0.12}
            isAnimationActive={false}
            name="최소~최대"
          />
          <Line
            dataKey="value"
            type="stepAfter"
            stroke="var(--primary)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            name="추가손실"
          />
          {held && (
            <Line
              dataKey="held"
              type="stepAfter"
              stroke="var(--success)"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
              name={held.label}
            />
          )}
          {marked && (
            <ReferenceLine
              x={deadline.last_day}
              stroke="var(--danger)"
              strokeDasharray="4 4"
              label={{ value: '결정 기한', position: 'insideTopRight', fill: 'var(--danger)', fontSize: 14 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
