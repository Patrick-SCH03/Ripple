// 한 단계 아래로 내린 설명(ⓘ 팝오버): 누르거나 탭하면 뜬다(마우스 올림만으로 보이게 하지 않음 — DESIGN.md 9절).
// 화면에 늘 떠 있던 보조 설명·계산 기준·조작 안내를 여기로 옮긴다(DESIGN.md 2절 '보조 한 줄 원칙').
// label이 있으면 아이콘 앞에 짧은 이름을 단 단추(예: '일정 악화 ⓘ'), 없으면 아이콘만.
import { Info } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

interface Props {
  /** 팝오버 제목(아이콘만일 때 단추 이름 '… 설명'). */
  title: string
  lines: readonly string[]
  /** 아이콘 앞 짧은 이름(있으면 글자 단추). */
  label?: string
  /** 글자 단추의 색: 주의(경고 색) · 보조(기본). */
  tone?: 'warning' | 'muted'
  className?: string
}

const ICON_ONLY =
  'inline-flex size-6 shrink-0 items-center pointer-coarse:-m-2.5 pointer-coarse:size-11 justify-center rounded-sm text-foreground-secondary hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

export function InfoPop({ title, lines, label, tone = 'muted', className }: Props) {
  return (
    <Popover>
      <PopoverTrigger
        aria-label={label ? undefined : `${title} 설명`}
        className={cn(
          label
            ? 'inline-flex min-h-6 items-center gap-1 rounded-sm text-sm underline decoration-dotted underline-offset-4 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:min-h-11'
            : ICON_ONLY,
          label && (tone === 'warning' ? 'text-warning' : 'text-foreground-secondary'),
          className,
        )}
      >
        {label}
        <Info aria-hidden className="size-3.5 shrink-0" />
      </PopoverTrigger>
      <PopoverContent>
        <p className="font-semibold">{title}</p>
        <ul className="mt-1.5 space-y-1 text-foreground-secondary">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
