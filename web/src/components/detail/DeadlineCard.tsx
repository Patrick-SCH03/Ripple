// 판단 요약 결정 기한 카드(DESIGN.md 6절, KeyNumbers 둘째 줄 맨 앞): 큰 D-n · 결재 올릴 기한 상자 · 일정 악화 경고 ·
// '하루 늦으면' 작은 곡선(누르면 곡선 탭) · 확정일과 결정 기한의 관계 한 줄과 '확정일을 ○월 ○일로' 단추(+ 되돌리기).
// 단추는 머리 확정일 칸과 같은 길(초안의 확정일을 고쳐 다시 분석)이고, 확정일을 바꿀 수 없을 때(계산 중·초안을 고침 등)는 그리지 않는다.
import { CircleCheck, Undo2 } from 'lucide-react'
import { useState } from 'react'
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { VALUE_TONE } from '@/components/common/numberCard'
import { SegmentText } from '@/components/common/SegmentText'
import { Button } from '@/components/ui/button'
import type { SubmitLine } from '@/lib/approval'
import { type DeadlineUndo, deadlineGuide, deadlineWorkday, guideText, showUndo, undoOf } from '@/lib/deadline'
import { formatDay } from '@/lib/format'
import { miniCurve } from '@/lib/miniCurve'
import type { KeyNumber } from '@/lib/summary'
import { CardLabel } from './CardLabel'
import { MiniLossCurve } from './MiniLossCurve'

// 결재 올릴 기한 줄: 단계당 1일로도 지났으면 위험, 대표만 지났으면 주의(아직 기한 안에 들 길이 있음)
const SUBMIT_TONE: Record<SubmitLine['tone'], string> = {
  late: 'text-danger',
  caution: 'text-warning',
  ok: 'text-foreground-secondary',
  none: 'text-foreground-secondary',
}
const SUBMIT_BOX: Record<SubmitLine['tone'], string> = {
  late: 'border-danger/40 bg-danger/8',
  caution: 'border-warning/50 bg-warning/10',
  ok: 'border-border bg-canvas',
  none: 'border-border bg-canvas',
}

export interface DeadlineCardProps {
  card: KeyNumber
  result: AnalysisResult
  /** 확정일을 바꿀 수 있는가(초안이 읽히고 표시 결과 = 초안). 아니면 결정 기한 단추를 숨긴다. */
  canEdit: boolean
  compact: boolean
  onConfirmOn: (date: string | null) => void
  /** 작은 곡선을 누르면: 추가손실 곡선 탭을 연다. */
  onOpenCurve: () => void
  /** 큰 숫자 아래 '결재 올릴 기한' 한 줄(서버 결재 계획, lib/approval submitLine). 없으면 그리지 않는다. */
  submit?: SubmitLine | null
}

/**
 * 보조 설명: 작은 곡선이 그려지면('하루 늦으면 +금액' · 기한 날짜) 같은 말을 되풀이하지 않게 보조 설명을 빼고,
 * 결정 기한이 주말일 때의 근무일만 남긴다(글 양 줄이기).
 */
function detailOf(card: KeyNumber, result: AnalysisResult): string | undefined {
  if (!miniCurve(result.timing.curve, result.timing.deadline)) return card.detail
  const workday = deadlineWorkday(result)
  return workday ? `근무일 기준 ${formatDay(workday)}` : undefined
}

export function DeadlineCard({ card, result, canEdit, compact, onConfirmOn, onOpenCurve, submit }: DeadlineCardProps) {
  const detail = detailOf(card, result)
  // 결재 올릴 기한 상자가 이미 주의·위험 색이면 일정 악화 경고 줄은 접는다(한 카드에 경고 하나)
  const folded = submit?.tone === 'late' || submit?.tone === 'caution'
  return (
    <div data-key-number={card.id} className="rounded-md border border-border bg-surface px-4 py-3">
      <CardLabel label={card.label} term={card.id} />
      {/* text-key는 cn으로 합치지 않는다(numberCard.ts) */}
      <p className={`mt-1 text-key font-semibold tabular-nums ${VALUE_TONE[card.tone]}`}>{card.value}</p>
      {/* 담당자가 실제로 지킬 날은 결재 올릴 기한: 큰 숫자 바로 아래 굵게(작은 곡선 아래에 두면 '지남'을 놓친다) */}
      {submit && (
        <p
          data-submit-by
          data-tone={submit.tone}
          className={`mt-2 rounded-sm border px-2 py-1.5 text-sm font-semibold ${SUBMIT_TONE[submit.tone]} ${SUBMIT_BOX[submit.tone]}`}
        >
          <SegmentText text={submit.text} keepAll />
        </p>
      )}
      {detail && <p className="mt-1 text-sm text-foreground-secondary">{detail}</p>}
      {card.caution &&
        (folded ? (
          // 경고 줄을 둘 세우지 않는다: 일정 악화 한 줄은 이름 단추 + ⓘ로(DESIGN.md 2절)
          <p data-caution className="mt-1">
            <InfoPop title="늦출수록 일정 악화" lines={[card.caution]} label="늦추면 일정 악화" tone="warning" />
          </p>
        ) : (
          <p data-caution className="mt-1 text-sm text-warning">
            {card.caution}
          </p>
        ))}
      <MiniLossCurve result={result} onOpen={onOpenCurve} />
      {/* 다시 분석하면 단추가 상태 한 줄로 바뀐다 — 알림 영역은 늘 두어 읽기 프로그램이 바뀐 글을 읽게 */}
      <div aria-live="polite">
        <DeadlineGuideRow result={result} canEdit={canEdit} compact={compact} onConfirmOn={onConfirmOn} />
      </div>
    </div>
  )
}

/** 단추 이름 속 날짜('10월 27일(화)')는 한 덩어리로 — 좁은 카드에서 '27일 / (화)로'처럼 끊기지 않게. */
function KeepDate({ text, date }: { text: string; date: string }) {
  const at = text.indexOf(date)
  if (at < 0) return text
  // 바깥 span 하나로 감싼다: 단추가 flex라 조각마다 따로 놓이면 글이 세로로 쪼개진다
  return (
    <span>
      {text.slice(0, at)}
      <span className="whitespace-nowrap">{date}</span>
      {text.slice(at + date.length)}
    </span>
  )
}

function DeadlineGuideRow({
  result,
  canEdit,
  compact,
  onConfirmOn,
}: Pick<DeadlineCardProps, 'result' | 'canEdit' | 'compact' | 'onConfirmOn'>) {
  // 단추로 확정일을 옮기기 전 값 — 다시 누르면(되돌리기) 그 확정일로 돌아간다(비워 둔 기준일이면 다시 비움)
  const [undo, setUndo] = useState<DeadlineUndo | null>(null)
  const guide = deadlineGuide(result)
  if (!guide) return null
  const { status, button } = guideText(guide, result.timing.deadline.kind)
  const target = guide.kind === 'on' ? null : guide.to
  const showButton = canEdit && button !== null && target !== null
  const canUndo = canEdit && showUndo(undo, result)
  if (!status && !showButton && !canUndo) return null
  // 카드가 좁으면(휴대폰 두 칸) 날짜가 든 이름이 넘치지 않게 줄을 바꾼다
  const buttonClass = `h-auto max-w-full whitespace-normal text-left ${compact ? 'min-h-11 px-3 py-1.5' : 'min-h-8 py-1'}`
  return (
    <div className="mt-2 space-y-1.5" data-testid="deadline-guide">
      {status && (
        <p className={`flex items-start gap-1 text-sm ${guide.kind === 'past' ? 'text-danger' : 'text-foreground-secondary'}`}>
          {guide.kind === 'on' && <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />}
          {status}
        </p>
      )}
      {showButton && (
        <Button
          size="sm"
          variant="outline"
          className={buttonClass}
          onClick={() => {
            setUndo(undoOf(result, target))
            onConfirmOn(target)
          }}
          data-testid="deadline-apply"
        >
          <KeepDate text={button} date={formatDay(target)} />
        </Button>
      )}
      {canUndo && (
        <Button
          size="sm"
          variant="ghost"
          className={buttonClass}
          onClick={() => {
            onConfirmOn(undo.confirm)
            setUndo(null)
          }}
          data-testid="deadline-undo"
        >
          <Undo2 aria-hidden />
          <KeepDate text={`되돌리기 · 확정일 ${formatDay(undo.day)}`} date={formatDay(undo.day)} />
        </Button>
      )}
    </div>
  )
}
