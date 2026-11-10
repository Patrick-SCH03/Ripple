// 결재 띠의 행동 단추: 강조는 다음 단계 하나, 대화상자를 거치는 행동은 '…', 진행 중이면 돌아가는 표시.
// 팀장이 다른 결재 단계(파트장·본부장)를 대신 결정하면 단추에 '(전결)'.
import { LoaderCircle } from 'lucide-react'
import type { EcnAction } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ACTION_LABEL, type ActionView } from '@/lib/records'

interface Props {
  actions: ActionView[]
  primary: (action: EcnAction) => boolean
  /** 보내는 중인 행동(있으면 모두 잠근다). */
  busy: EcnAction | null
  /** 결재 상태를 다시 맞추는 중(잠근다). */
  syncing: boolean
  onRun: (action: EcnAction) => void
}

export function ApprovalActions({ actions, primary, busy, syncing, onRun }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {actions.map((view) => (
        <Button
          key={view.action}
          size="lg"
          className="px-4 text-base"
          variant={primary(view.action) ? 'default' : 'outline'}
          disabled={!view.enabled || busy !== null || syncing}
          onClick={() => onRun(view.action)}
          data-testid={`flow-${view.action}`}
        >
          {busy === view.action && <LoaderCircle aria-hidden className="animate-spin" />}
          {ACTION_LABEL[view.action]}
          {view.proxy && '(전결)'}
          {view.dialog && '…'}
        </Button>
      ))}
    </div>
  )
}
