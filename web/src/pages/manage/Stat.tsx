// 결재·현황의 수치 카드(DESIGN.md 6절 '숫자 카드'): 이름 + 큰 숫자. 보조 줄은 그 숫자만으로는 모르는데 바로 행동이 바뀌는
// 정보 한 줄까지(없으면 두지 않음). 항목 나열·분석용 세부는 이름 옆 ⓘ(more)로 내린다.
import { InfoPop } from '@/components/common/InfoPop'
import { VALUE_TONE, type ValueTone } from '@/components/common/numberCard'

export function Stat({
  label,
  value,
  detail,
  more,
  tone = 'neutral',
}: {
  label: string
  value: string
  /** 행동이 바뀌는 보조 한 줄(짧게, 줄바꿈 없이). 큰 숫자를 말로 되풀이하는 줄은 두지 않는다. */
  detail?: string
  /** 이름 옆 ⓘ에 넣을 세부(항목 나열·중앙값 같은 분석용). */
  more?: readonly string[]
  tone?: ValueTone
}) {
  return (
    <div className="rounded-md border border-border bg-surface px-4 py-3">
      <div className="flex min-h-6 items-center gap-0.5">
        <p className="truncate text-sm text-foreground-secondary" title={label}>{label}</p>
        {more && more.length > 0 && <InfoPop title={label} lines={more} />}
      </div>
      {/* text-key는 cn으로 합치지 않는다(numberCard.ts) */}
      <p className={`text-key font-semibold tabular-nums ${VALUE_TONE[tone]}`}>{value}</p>
      {detail && <p className="truncate text-sm font-medium text-foreground tabular-nums">{detail}</p>}
    </div>
  )
}
