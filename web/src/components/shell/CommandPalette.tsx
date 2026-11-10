// 명령 팔레트(Ctrl/⌘+K): 설계변경 고르기 · 이번 결과의 엔터티 찾기 · 화면 동작.
import { FileText } from 'lucide-react'
import { useRef } from 'react'
import type { ImpactView, Sample } from '@/api/client'
import { CommandDialog, Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { useReturnFocus } from '@/lib/focus'
import { ENTITY_NAMES, nameOf } from '@/lib/labels'
import type { PaletteCommand } from '@/state/useCommandPalette'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  samples: Sample[]
  onChoose: (sample: Sample) => void
  report: ImpactView | null
  onSelectNode: (id: string) => void
  actions: PaletteCommand[]
}

export function CommandPalette({ open, onOpenChange, samples, onChoose, report, onSelectNode, actions }: Props) {
  const returnFocus = useReturnFocus(open)
  // 엔터티를 고르면 상세가 근거 제목으로 초점을 옮기므로(영향 지도 그래프를 막 불러오는 중이면 조금 뒤에) 연 자리로 돌려주지 않는다
  const toEvidence = useRef(false)
  const closeFocus = (event: Event) => {
    if (!toEvidence.current) return returnFocus(event)
    toEvidence.current = false
    event.preventDefault()
  }
  // 고르면 팔레트를 닫고 실행한다(동작이 초점을 옮기지 않았으면 연 자리로 돌아간다)
  const pick = (run: () => void) => () => {
    onOpenChange(false)
    run()
  }
  const pickNode = (id: string) => {
    toEvidence.current = true
    onOpenChange(false)
    onSelectNode(id)
  }
  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="찾기"
      description="설계변경·부재·발주를 이름이나 번호로 찾기"
      className="sm:max-w-xl"
      onCloseAutoFocus={closeFocus}
    >
      <Command loop>
        <CommandInput placeholder="ECN 번호, 부재·발주 이름…" />
        <CommandList>
          <CommandEmpty>찾는 것 없음</CommandEmpty>
          {samples.length > 0 && (
            <CommandGroup heading="설계변경">
              {samples.map((sample) => (
                <CommandItem key={sample.ecn_id} value={`ecn ${sample.ecn_id} ${sample.title}`} onSelect={pick(() => onChoose(sample))}>
                  <FileText aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{sample.title}</span>
                  <span className="font-mono text-xs text-foreground-secondary">{sample.ecn_id}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {report && report.graph.nodes.length > 0 && (
            <CommandGroup heading="이번 결과의 엔터티">
              {report.graph.nodes.map((node) => (
                <CommandItem
                  key={node.id}
                  value={`node ${node.id} ${node.label} ${nameOf(ENTITY_NAMES, node.type)}`}
                  onSelect={() => pickNode(node.id)}
                >
                  <span className="min-w-0 flex-1 truncate">{node.label}</span>
                  <span className="text-xs text-foreground-secondary">{nameOf(ENTITY_NAMES, node.type)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {actions.length > 0 && (
            <CommandGroup heading="화면">
              {actions.map((action) => (
                <CommandItem key={action.id} value={`action ${action.label}`} onSelect={pick(action.run)}>
                  <action.icon aria-hidden />
                  {action.label}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  )
}
