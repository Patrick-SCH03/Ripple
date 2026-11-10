// 넓은 화면의 3D 배치: 3D(위·왼쪽) + 근거(아래·오른쪽). 판 폭 1100px 이상이면 옆, 아니면 위아래(2D 지도와 같은 기준).
// three 묶음과 함께 이 칸을 처음 열 때 따로 불러온다(RipplePanel의 lazy). 칸 경계는 배치(옆·위아래)마다 이 브라우저에
// 기억한다(useDefaultLayout + safeStorage — 2D 지도와 같은 방식, 키는 ripple.detail.map3d[.side]).
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { useDefaultLayout } from 'react-resizable-panels'
import type { ImpactView } from '@/api/client'
import { EvidencePanel } from '@/components/EvidencePanel'
import { useFullscreen } from '@/components/graph/useFullscreen'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { safeStorage } from '@/lib/storage'
import { Ship3DView } from './Ship3DView'

/** 이 폭 이상이면 근거를 옆에(2D 지도 lib/graphModel MAP_LAYOUT.minWidth와 같은 값 — dagre를 이 묶음에 끌어오지 않게 따로 둔다). */
const SIDE_MIN_WIDTH = 1100

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
}

export default function Ship3DWorkspace({ report, selected, onSelect }: Props) {
  const frame = useRef<HTMLDivElement>(null)
  const canClose = useCallback(() => selected === null, [selected])
  const fullscreen = useFullscreen(frame, canClose)
  const [side, setSide] = useState<boolean | null>(null)
  useLayoutEffect(() => {
    const element = frame.current
    if (!element) return
    const check = () => setSide(element.getBoundingClientRect().width >= SIDE_MIN_WIDTH)
    check()
    const resize = new ResizeObserver(check)
    resize.observe(element)
    return () => resize.disconnect()
  }, [])
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: side ? 'ripple.detail.map3d.side' : 'ripple.detail.map3d',
    storage: safeStorage,
  })

  return (
    <div
      ref={frame}
      className={fullscreen.overlay ? 'fixed inset-0 z-50 flex flex-col bg-surface' : 'relative min-h-0 flex-1 bg-surface'}
      aria-label={fullscreen.full ? '3D 배치 전체 화면' : undefined}
      role={fullscreen.full ? 'region' : undefined}
    >
      {side !== null && (
        <ResizablePanelGroup
          key={side ? 'side' : 'below'}
          orientation={side ? 'horizontal' : 'vertical'}
          defaultLayout={defaultLayout}
          onLayoutChanged={onLayoutChanged}
        >
          <ResizablePanel id="ship" defaultSize={side ? '66%' : '64%'} minSize={side ? '45%' : '35%'}>
            <Ship3DView
              report={report}
              selected={selected}
              onSelect={onSelect}
              full={fullscreen.full}
              onToggleFull={fullscreen.toggle}
            />
          </ResizablePanel>
          <ResizableHandle aria-label={side ? '3D 배치와 근거 폭 조절' : '3D 배치와 근거 높이 조절'} />
          <ResizablePanel id="evidence" minSize={side ? '340px' : '20%'} style={{ overflow: 'auto' }}>
            <EvidencePanel report={report} selected={selected} onSelect={onSelect} />
          </ResizablePanel>
        </ResizablePanelGroup>
      )}
    </div>
  )
}
