// 빠른 로그인(시연 배포 전용, docs/operations.md(서비스) 2절): 아이디·비밀번호 대신 역할 단추 둘(담당자 → 파트장, 결재선 첫
// 단계까지). 시연은 설계변경 한 건의 영향 추적·계산이 중심이라 팀장·본부장 단추는 두지 않는다(결재선은 화면의 진행
// 표시로만, 서버 고정 계정은 시드·결재선 진행에 그대로). 누르면 그 역할의 고정 계정으로 들어가고, 첫 화면은 기존 흐름대로
// (결재자 = 결재·현황, 담당자 = 업무 화면 — lib/route.ts).
import { ChevronRight, LoaderCircle, UserRoundCheck, UserRoundPen, type LucideIcon } from 'lucide-react'
import { useId } from 'react'
import type { QuickRole } from '@/api/client'

interface Choice {
  role: QuickRole
  icon: LucideIcon
  title: string
  detail: string
}

// 이름(김설계·이파트장)은 서버 상수 ripple/auth/quick.py QUICK_ACCOUNTS와 맞춰야 한다(서버가 로그인 때마다 그 값으로 되돌림).
const CHOICES: readonly Choice[] = [
  {
    role: 'member',
    icon: UserRoundPen,
    title: '담당자로 들어가기',
    detail: '김설계 · 설계변경 영향을 분석하고 결재선에 검토를 요청합니다',
  },
  {
    role: 'part_lead',
    icon: UserRoundCheck,
    title: '파트장으로 들어가기',
    detail: '이파트장 · 같은 분석 결과를 보고 결재선 첫 단계를 결재합니다',
  },
]

interface Props {
  /** 지금 들어가는 중인 역할(없으면 null). 누르는 동안 모든 단추를 막는다. */
  busy: QuickRole | null
  onChoose: (role: QuickRole) => void
}

export function QuickChoices({ busy, onChoose }: Props) {
  const base = useId()
  return (
    <div className="flex flex-col gap-3" role="group" aria-label="역할 골라 들어가기">
      {CHOICES.map(({ role, icon: Icon, title, detail }) => {
        const pressed = busy === role
        return (
          <button
            key={role}
            type="button"
            onClick={() => onChoose(role)}
            disabled={busy !== null}
            aria-label={title}
            aria-describedby={`${base}-${role}`}
            aria-busy={pressed}
            className="flex min-h-16 w-full items-center gap-3 rounded-md border border-border bg-surface px-4 py-3 text-left transition-colors outline-none hover:border-border-strong hover:bg-hover focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-border disabled:hover:bg-surface"
            data-testid={`quick-${role}`}
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon className="size-5" aria-hidden />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-md font-semibold text-foreground">{title}</span>
              <span id={`${base}-${role}`} className="text-sm text-foreground-secondary">
                {pressed ? '들어가는 중입니다…' : detail}
              </span>
            </span>
            {pressed ? (
              <LoaderCircle className="size-4 shrink-0 animate-spin text-foreground-secondary" aria-hidden />
            ) : (
              <ChevronRight className="size-4 shrink-0 text-foreground-secondary" aria-hidden />
            )}
          </button>
        )
      })}
    </div>
  )
}
