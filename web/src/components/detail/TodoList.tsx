// 할 일 > 조치(DESIGN.md 2·6절): 적용한 보류 · 보류 권고 · 후행 설치 선택지 · 발주 손실 보상 협의 · 자재 전용.
// 한 줄 요약 + 오른쪽 실행 단추. 보류 적용·빼기와 후행 설치 전환은 가정 계산(요청을 바꿔 다시 분석)이고, 표시 결과가
// 지금 초안의 결과일 때만 누를 수 있다. 할 일 칸(ActionsSection) 안의 첫 묶음이라 제목은 묶음 이름(h4).
import { Archive, CirclePause, HandCoins, PackageCheck, Ship, type LucideIcon } from 'lucide-react'
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { TermInfo } from '@/components/common/TermInfo'
import { Button } from '@/components/ui/button'
import { todoText, todos, type Todo } from '@/lib/summary'
import { SubSection } from './DetailSection'

interface Props {
  result: AnalysisResult
  /** 표시 결과 = 초안(current)일 때만 보류를 바꿀 수 있다. */
  canChange: boolean
  onHold: (poId: string, days: number | null) => void
  /** 후행 설치를 켜거나(true) 끄고(false) 다시 계산한다(명세 6-8). */
  onOnboard: (on: boolean) => void
}

const ICONS: Record<Todo['kind'], LucideIcon> = {
  held: CirclePause,
  hold: Archive,
  onboard: Ship,
  consult: HandCoins,
  reallocation: PackageCheck,
}

function keyOf(todo: Todo): string {
  if (todo.kind === 'held') return `held-${todo.poId}`
  if (todo.kind === 'hold') return `hold-${todo.advice.po_id}`
  if (todo.kind === 'onboard') return 'onboard'
  if (todo.kind === 'consult') return 'consult'
  return `realloc-${todo.item.lot_id}-${todo.item.to_block_id}`
}

export function TodoList({ result, canChange, onHold, onOnboard }: Props) {
  const items = todos(result)
  if (items.length === 0) return null
  const holds = items.some((todo) => todo.kind === 'held' || todo.kind === 'hold')
  const onboard = items.some((todo) => todo.kind === 'onboard')
  return (
    // 할 일 카드의 첫 소구역(소제목 + 줄). 설명 단추는 제목 밖에 둔다: 안에 두면 제목·구역 이름에 단추 이름이 섞인다
    // 시연 대본이 이 이름으로 찾는다(lib/demoScenarios DEMO_SELECTORS.todo — 검사가 소스에서 글자 그대로 찾음)
    <div data-testid="todo-actions">
      <SubSection id="todo-title" title={`조치 ${items.length}`} info={holds && <TermInfo term="hold" />} first>
        <ul className="divide-y divide-border rounded-md border border-border">
          {items.map((todo) => {
            const Icon = ICONS[todo.kind]
            const text = todoText(todo, result.timing.deadline, result.approval_plan)
            return (
              <li key={keyOf(todo)} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
                <Icon aria-hidden className="size-4 shrink-0 text-foreground-secondary" />
                <div className="min-w-0 flex-1">
                  <p className="text-base font-medium">
                    {text.title}
                    {/* 후행 설치 설명은 그 줄에(제목 옆에 두면 보류 설명과 같은 아이콘이 나란히 놓여 헷갈림) */}
                    {todo.kind === 'onboard' && <TermInfo term="onboard" />}
                  </p>
                  {/* 보조는 한 줄: 결재 기간 안 보류 가능 여부는 그 줄 끝 '결재 기간 ⓘ'(DESIGN.md 2절) */}
                  <p className="text-sm text-foreground-secondary">
                    {text.detail}
                    {text.note && (
                      <span className="ml-1.5 inline-block" data-testid="hold-approval">
                        <InfoPop title="결재 기간과 보류" lines={[text.note]} label="결재 기간" />
                      </span>
                    )}
                  </p>
                </div>
                {todo.kind === 'hold' && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!canChange}
                    onClick={() => onHold(todo.advice.po_id, todo.advice.max_hold_days)}
                  >
                    보류 적용
                  </Button>
                )}
                {todo.kind === 'onboard' && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!canChange}
                    onClick={() => onOnboard(todo.option.direction === 'to_on_board')}
                  >
                    {todo.option.direction === 'to_on_board' ? '후행 설치로 계산' : '기다리는 방식으로 계산'}
                  </Button>
                )}
                {todo.kind === 'held' && (
                  <Button size="sm" variant="outline" disabled={!canChange} onClick={() => onHold(todo.poId, null)}>
                    보류 빼기
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
        {/* '단추는 가정 계산'은 보류·후행 설치 ⓘ에 있다 — 흐린 단추일 때만 이유 한 줄 */}
        {(holds || onboard) && !canChange && (
          <p className="mt-1.5 text-sm text-foreground-secondary">지금 초안으로 다시 계산 후 변경 가능</p>
        )}
      </SubSection>
    </div>
  )
}
