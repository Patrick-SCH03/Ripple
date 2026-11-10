// 대화상자 맨 위 큰 숫자 칸(결정 도우미 카드와 같은 원칙 — DESIGN.md 2절 숫자 카드): 이름 · 큰 숫자 · 행동 한 줄까지.
// 범위·계산식은 칸에 두지 않고 아래 표에 남긴다.
import { VALUE_TONE, type ValueTone } from './numberCard'
import { SegmentText } from './SegmentText'

export interface GlanceTile {
  id: string
  label: string
  value: string
  line?: string | null
  tone?: ValueTone
}

export function GlanceTiles({ tiles, testId }: { tiles: readonly GlanceTile[]; testId?: string }) {
  if (tiles.length === 0) return null
  return (
    <div className="grid grid-cols-2 gap-2" data-testid={testId}>
      {tiles.map((tile) => (
        <div key={tile.id} data-glance={tile.id} className="flex min-w-0 flex-col justify-center rounded-md border border-border bg-surface px-3 py-2">
          <p className="text-sm font-medium text-foreground-secondary">{tile.label}</p>
          {/* text-key는 cn으로 합치지 않는다(numberCard.ts) */}
          <p className={`text-key leading-tight font-bold whitespace-nowrap tabular-nums ${VALUE_TONE[tile.tone ?? 'neutral']}`}>{tile.value}</p>
          {tile.line && (
            <p className="mt-0.5 text-sm font-medium tabular-nums">
              <SegmentText text={tile.line} />
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
