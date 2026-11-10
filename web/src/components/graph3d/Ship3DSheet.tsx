// 좁은 화면(현장 태블릿·휴대폰)의 3D 배치: 영향 목록 아래 단추 하나로 전체 화면 대화상자에서만 연다(DESIGN.md 7절 —
// 좁은 화면은 들여쓴 목록이 기본). 블록을 누르면 아래 띠에 블록 요약, '근거 보기'로 닫고 목록 아래 근거로 간다.
import { useMemo } from 'react'
import type { ImpactView } from '@/api/client'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import { Button } from '@/components/ui/button'
import { DialogClose, DialogTitle } from '@/components/ui/dialog'
import { blockStates } from './blocks'
import { selectedBlock } from './focus'
import { BLOCK_LAYOUT } from './layout'
import { Ship3DView } from './Ship3DView'

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
  /** 닫고 근거로(목록 아래 근거 제목에 초점). */
  onEvidence: () => void
}

export default function Ship3DSheet({ report, selected, onSelect, onEvidence }: Props) {
  const { placed } = useMemo(() => blockStates(report), [report])
  const code = selectedBlock(report, selected)
  const state = code ? placed.get(code) : undefined
  const place = BLOCK_LAYOUT.find((block) => block.code === code)
  const footer = (
    <div className="flex shrink-0 items-center gap-2 border-t border-border px-3 py-2" aria-live="polite">
      {state && place ? (
        <>
          <p className="min-w-0 flex-1 text-sm">
            <span className="font-mono font-medium">{place.code}</span> {place.name}
            {state.impacts > 0 && <span className="text-foreground-secondary"> · 영향 {state.impacts}건</span>}
          </p>
          {state.severity && <SeverityBadge severity={state.severity} />}
          <Button className="h-11" onClick={onEvidence}>
            근거 보기
          </Button>
        </>
      ) : (
        <p className="text-sm text-foreground-secondary">블록을 누르면 근거</p>
      )}
    </div>
  )
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-1.5">
        <DialogTitle className="flex-1 text-md font-medium">3D 배치</DialogTitle>
        <DialogClose asChild>
          <Button variant="outline" className="h-11">
            닫기
          </Button>
        </DialogClose>
      </div>
      <div className="min-h-0 flex-1">
        <Ship3DView report={report} selected={selected} onSelect={onSelect} full touch footer={footer} />
      </div>
    </div>
  )
}
