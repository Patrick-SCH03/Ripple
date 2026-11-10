// 영향 지도 아래 띠: '2D 영향 지도 | 3D 배치' 전환(첫 화면 묶음 — three는 여기서 불러오지 않는다).
// 지도 칸 안의 첫 단추가 되지 않게 지도 아래에 두고, 단추마다 data-graph-toggle(시연 대본 선택자와 구분).
import { Box, Network } from 'lucide-react'
import { useEffect } from 'react'
import { cn } from '@/lib/utils'
import type { MapView } from './webgl'

interface Props {
  view: MapView
  onView: (view: MapView) => void
  /** 3D를 쓸 수 없어 2D로 돌아왔을 때 안내. */
  notice: string | null
}

export function MapViewSwitch({ view, onView, notice }: Props) {
  const options: { value: MapView; label: string; icon: typeof Box }[] = [
    { value: '2d', label: '2D 영향 지도', icon: Network },
    { value: '3d', label: '3D 배치', icon: Box },
  ]
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-3 py-1.5">
      <div role="group" aria-label="영향 지도 보기" className="flex overflow-hidden rounded-md border border-border-strong">
        {options.map(({ value, label, icon: Icon }, i) => (
          <button
            key={value}
            type="button"
            data-graph-toggle={value}
            aria-pressed={view === value}
            onClick={() => onView(value)}
            className={cn(
              'inline-flex h-9 items-center gap-1.5 px-2.5 text-sm font-medium transition-colors focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-ring',
              i > 0 && 'border-l border-border-strong',
              view === value ? 'bg-secondary text-foreground' : 'bg-surface text-foreground-secondary hover:bg-hover',
            )}
          >
            <Icon aria-hidden className="size-4" />
            {label}
          </button>
        ))}
      </div>
      {/* 3D 읽는 법(가상 배치 · 블록 색)은 영향 범위 머리 ⓘ(mapUse) 한 곳에 — 여기는 2D로 돌아온 이유만 */}
      {notice && (
        <p role="status" className="text-sm text-warning">
          {notice}
        </p>
      )}
    </div>
  )
}

/** 3D 장면을 만들지 못했을 때(WebGL 없음·장면 오류): 그리는 순간 2D로 돌리고 안내를 남긴다. */
export function Unavailable({ onUnavailable }: { onUnavailable: () => void }) {
  useEffect(() => onUnavailable(), [onUnavailable])
  return <p className="p-6 text-sm text-foreground-secondary">3D 보기를 쓸 수 없는 브라우저 · 2D 영향 지도로 전환</p>
}
