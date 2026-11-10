// 설계변경 목록이 없는 지도(엑셀로 가져온 지도)의 목록 칸: 분석 기준(호선·기준일)과 AI 비서 안내.
// 분석 기준은 비서가 새 요청에 쓰는 유일한 출처다(lib/basis). 기준일 기본값은 자료 기준일(지도 안의 마지막 상태 기록).
import { MessagesSquare } from 'lucide-react'
import type { SnapshotInfo } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { basisNote, type Basis } from '@/lib/basis'
import { formatDay } from '@/lib/format'
import { cn } from '@/lib/utils'

interface Props {
  info: SnapshotInfo
  basis: Basis
  onBasis: (basis: Basis) => void
  onAssistant: () => void
  /** 좁은 화면: 터치 높이. */
  compact: boolean
}

export function MapBasisPanel({ info, basis, onBasis, onAssistant, compact }: Props) {
  const note = basisNote(basis, info)
  const many = info.ship_ids.length > 1
  const toggle = (shipId: string, on: boolean) => {
    const chosen = new Set(basis.shipIds)
    if (on) chosen.add(shipId)
    else chosen.delete(shipId)
    onBasis({ ...basis, shipIds: info.ship_ids.filter((id) => chosen.has(id)) })
  }
  return (
    <div className="space-y-4 p-4 text-sm" data-testid="map-basis">
      <section aria-labelledby="basis-title" className="space-y-3">
        <div>
          <h3 id="basis-title" className="font-semibold">
            분석 기준
          </h3>
          <p className="text-foreground-secondary">AI 비서가 새 설계변경을 이 호선·기준일로 분석</p>
        </div>
        {many ? (
          <fieldset className="space-y-1">
            <legend className="mb-1 text-foreground-secondary">호선</legend>
            {info.ship_ids.map((shipId) => (
              <label key={shipId} className={cn('flex items-center gap-2', compact && 'min-h-11')}>
                <input
                  type="checkbox"
                  checked={basis.shipIds.includes(shipId)}
                  onChange={(event) => toggle(shipId, event.target.checked)}
                  className="size-4 accent-[var(--primary)]"
                />
                <span className="font-mono">{shipId}</span>
              </label>
            ))}
            {basis.shipIds.length === 0 && <p className="text-danger">호선 1개 이상 선택 필요</p>}
          </fieldset>
        ) : (
          <p>
            <span className="text-foreground-secondary">호선 </span>
            <span className="font-mono">{info.ship_ids[0] ?? '—'}</span>
          </p>
        )}
        <label className="flex flex-wrap items-center gap-2">
          <span className="text-foreground-secondary">기준일</span>
          <Input
            type="date"
            value={basis.asOf}
            onChange={(event) => onBasis({ ...basis, asOf: event.target.value })}
            className={cn('w-auto rounded-sm tabular-nums md:text-sm', compact ? 'h-11' : 'h-9')}
            aria-describedby="basis-data-date"
          />
        </label>
        <p id="basis-data-date" className="text-foreground-secondary">
          {info.status_date
            ? `자료 기준일 ${formatDay(info.status_date)}(지도 안의 마지막 상태 기록)`
            : '자료 기준일 없음(상태 기록이 없는 지도)'}
        </p>
        {note && <p className="text-warning">{note}</p>}
        {!basis.asOf && <p className="text-danger">기준일 선택 필요</p>}
      </section>
      <section className="space-y-2 border-t border-border pt-4">
        <p className="text-foreground-secondary">
          설계변경 목록 없음 · AI 비서에 바꿀 대상과 값을 적으면 이 기준으로 분석
        </p>
        <Button variant="outline" onClick={onAssistant} className={cn(compact && 'h-11')}>
          <MessagesSquare aria-hidden />
          AI 비서에 적기
        </Button>
      </section>
    </div>
  )
}
