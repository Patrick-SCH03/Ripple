// 핵심 수치 카드 머리: 이름 + 용어 설명 ⓘ(DESIGN.md 9절). 첫 줄 큰 카드는 한 단계 큰 이름(className으로).
import { TermInfo } from '@/components/common/TermInfo'
import type { TermId } from '@/lib/glossary'

export function CardLabel({
  label,
  term,
  className = 'text-sm text-foreground-secondary',
}: {
  label: string
  term: TermId
  className?: string
}) {
  return (
    <div className="-my-1 flex items-center gap-0.5">
      <p className={className}>{label}</p>
      <TermInfo term={term} />
    </div>
  )
}
