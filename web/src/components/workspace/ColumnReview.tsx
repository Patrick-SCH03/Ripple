// 엑셀 가져오기 '열 확인' 단계(docs/input.md(엑셀 양식) 4절, DESIGN.md 6절 엑셀 가져오기 대화상자).
// 위에 남은 일(읽기 전에 정할 것 · 확인할 것), 아래로 시트 카드(정할 것이 많은 시트부터). 시트마다 양식 시트 고르기(읽지 않음
// 포함)·머리글 행 고르기(앞 행 미리보기), 열마다 파일 머리글·예시 값 → 양식 항목 · 원본 단위. 자동으로 맞춘 열은 접는다.
// 판단 확률·경로 이름·보정 판 같은 개발용 정보는 보이지 않고, 상태는 아이콘 + 글자로만(자동 · 확인 · 선택 필요 ·
// 단위 선택 필요 · 다른 열과 겹침 · 고침). 시트 카드·열 줄·머리글 고르기는 columnReview/.
import type { MappingProposal } from '@/api/client'
import { pending, sheetOrder, type Choices, type ColumnChoice, type Pending } from '@/lib/mapping'
import { cn } from '@/lib/utils'
import { SheetCard } from './columnReview/SheetCard'

interface Props {
  proposal: MappingProposal
  choices: Choices
  /** 시트 상태를 다시 제안받는 중 */
  busy: boolean
  onColumn: (sheet: string, position: number, choice: ColumnChoice) => void
  /** 시트 상태(양식 시트·읽지 않음)·머리글 행을 정해 다시 제안받는다. headerRows가 null이면 서버가 다시 찾는다. */
  onSheet: (sheet: string, template: string | null, headerRows: number[] | null) => void
}

export function ColumnReview({ proposal, choices, busy, onColumn, onSheet }: Props) {
  const left = pending(proposal, choices)
  return (
    <div className="space-y-3" data-testid="column-review">
      <Summary proposal={proposal} left={left} />
      {sheetOrder(proposal, choices).map((sheet) => {
        const choice = choices[sheet.file_sheet]
        if (!choice) return null
        return (
          <SheetCard
            key={sheet.file_sheet}
            proposal={proposal}
            sheet={sheet}
            choice={choice}
            missing={left.missing[sheet.file_sheet] ?? []}
            busy={busy}
            onColumn={onColumn}
            onSheet={onSheet}
          />
        )
      })}
    </div>
  )
}

function Summary({ proposal, left }: { proposal: MappingProposal; left: Pending }) {
  const autos = proposal.sheets.reduce((n, s) => n + (s.template ? s.columns.filter((c) => c.auto).length : 0), 0)
  if (proposal.exact) {
    return (
      <div className="rounded-md border border-success/40 bg-success/8 px-3 py-2" role="status">
        <p className="font-semibold">모든 시트·열이 지정 양식과 같음</p>
        <p className="mt-0.5 text-foreground-secondary">이대로 읽기 → 품질 리포트</p>
      </div>
    )
  }
  return (
    <div
      role="status"
      className={cn(
        'rounded-md border px-3 py-2',
        left.blocking ? 'border-warning/40 bg-warning/8' : 'border-primary/40 bg-primary/8',
      )}
    >
      <p className="font-semibold" data-testid="review-left">
        {left.blocking ? `읽기 전에 정할 것 ${left.blocking}개` : '정할 것 없음'}
      </p>
      <p className="mt-0.5 text-foreground-secondary">
        확인할 것 {left.review}개 · 자동으로 맞춘 열 {autos}개
      </p>
      <p className="mt-0.5 text-xs text-foreground-secondary">자동 맞춤 기준: {proposal.calibration}</p>
    </div>
  )
}
