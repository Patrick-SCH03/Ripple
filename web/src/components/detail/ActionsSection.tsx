// 할 일 구역의 조치 묶음(DESIGN.md 2·6절): '해야 할 일'과 '판단이 걸린 상태'를 한 칸으로 합친다 — 이름이 비슷해 헷갈렸다.
// 묶음 둘: 조치(이 변경에 대해 할 수 있는 일 — 보류·후행 설치·협의·전용)와 계산에 쓴 현장 상태(발주·공정 상태 — 구매·
// 생산관리 확인 대상, 처음에는 접힘). 둘 다 없으면 그리지 않는다. 기록한 분석이면 맨 위에 결재선 안내 한 줄(추가 비용 건 = 파트장 → 팀장 →
// 본부장, 무비용 = 담당자 처리 — 서버 결재 계획, docs/records.md(기록·결재) 14절). 구역 머리(제목·조치 수)는 EcnDetail의 구역 카드가 그린다.
import { Stamp } from 'lucide-react'
import type { AnalysisResult, StatusUpdate } from '@/api/client'
import { hasActions } from '@/lib/detailNav'
import { StateBasisCard } from './StateBasisCard'
import { TodoList } from './TodoList'

interface Props {
  result: AnalysisResult
  compact: boolean
  /** 표시 결과 = 지금 초안일 때만 조치(가정 계산)를 바꿀 수 있다. */
  canChange: boolean
  onHold: (poId: string, days: number | null) => void
  onOnboard: (on: boolean) => void
  today: string
  canConfirm: boolean
  onStatusUpdate: (update: StatusUpdate) => Promise<string | null>
  /** 결재선 안내 한 줄(lib/approval lineGuide). 없으면 그리지 않는다. */
  approval?: string | null
}

export function ActionsSection({
  result,
  compact,
  canChange,
  onHold,
  onOnboard,
  today,
  canConfirm,
  onStatusUpdate,
  approval = null,
}: Props) {
  if (!hasActions(result, approval)) return null
  return (
    <div className="space-y-4" data-testid="actions">
      {/* 결재선 한 줄: 상자 없이 본문 크기로(구역 머리 바로 아래 — 이 건이 거칠 결재) */}
      {approval && (
        <p className="flex items-center gap-2 text-base" data-testid="approval-guide">
          <Stamp aria-hidden className="size-4 shrink-0 text-foreground-secondary" />
          {approval}
        </p>
      )}
      <TodoList result={result} canChange={canChange} onHold={onHold} onOnboard={onOnboard} />
      <StateBasisCard result={result} compact={compact} today={today} canConfirm={canConfirm} onSubmit={onStatusUpdate} />
    </div>
  )
}
