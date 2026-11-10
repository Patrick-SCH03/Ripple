// 상세 머리: 제목 · 작은 메타 줄(ECN 번호·호선·기준일) · 확정일 · 설계 승인·적용 시작일·변경 원인 · 판정 띠(판정 색 바탕,
// 판정 이름 + 짧은 이유 — 머리에서 가장 먼저 눈에 띄게) + 오른쪽 동작(요약 복사).
// 머리 글은 표시 중인 결과가 답한 요청으로, 고르기 칸은 초안으로 그린다(계산 중에 초안과 결과가 섞이지 않게).
// 휴대폰 폭(640px 미만)은 조회가 먼저라 분석 조건 칸을 한 줄 요약으로 접고 '조건 바꾸기'로 편다(판정이 첫 화면에 오게).
// 기준일·확정일·설계 승인·적용 시작일·변경 원인은 라벨 옆 ⓘ로 뜻을 본다(날짜마다 계산에 쓰는지가 달라 헷갈리기 쉽다).
import { ChevronDown, Lock } from 'lucide-react'
import { Fragment, useId, useState, type ReactNode } from 'react'
import type { Verdict } from '@/api/client'
import { TermInfo } from '@/components/common/TermInfo'
import { VerdictBand } from '@/components/common/VerdictBadge'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { formatDay } from '@/lib/format'
import type { TermId } from '@/lib/glossary'
import {
  CHANGE_CAUSES,
  CHANGE_CAUSE_NAMES,
  DESIGN_STATUSES,
  DESIGN_STATUS_NAMES,
  conditionSummary,
  type ChangeCause,
  type DesignStatus,
  type RequestContext,
} from '@/lib/request'
import { cn } from '@/lib/utils'
import { CauseNote } from './CauseNote'

/** 조건 칸 하나: 라벨 · ⓘ · 입력. ⓘ 단추는 label 밖에 둔다(안에 두면 라벨이 단추와 이어져 입력과 끊긴다). */
function Field({
  id,
  label,
  term,
  className,
  children,
}: {
  id: string
  label: string
  term: TermId
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className="flex items-center gap-0.5">
        <label htmlFor={id} className="text-foreground-secondary">
          {label}
        </label>
        <TermInfo term={term} />
      </span>
      {children}
    </div>
  )
}

interface HeaderProps {
  /** 머리 글은 표시 중인 결과가 답한 요청으로 그린다(초안과 섞이지 않게). */
  shown: RequestContext
  /** 확정일 고르기는 초안을 고친다. */
  draft: RequestContext
  editable: boolean
  /** 결재 중·결정된 건의 조건 잠금 한 줄(lib/records conditionLock). 있으면 칸 아래 자물쇠와 함께. */
  lockNote?: string | null
  verdict: Verdict | null
  /** 판정 줄 오른쪽 동작(요약 복사) — 따로 한 줄을 차지하지 않게. */
  actions?: ReactNode
  onConfirmOn: (date: string | null) => void
  onDesignStatus: (status: DesignStatus) => void
  onEffectiveOn: (date: string | null) => void
  onCause: (cause: ChangeCause | null) => void
}

export function DetailHeader({
  shown,
  draft,
  editable,
  lockNote = null,
  verdict,
  actions,
  onConfirmOn,
  onDesignStatus,
  onEffectiveOn,
  onCause,
}: HeaderProps) {
  const [conditionsOpen, setConditionsOpen] = useState(false)
  const ids = useId()
  const meta = [
    shown.ecnId && (
      <span key="ecn" className="font-mono" data-testid="detail-ecn">
        {shown.ecnId}
      </span>
    ),
    shown.shipIds.length > 0 && (
      <span key="ships">
        호선 <span className="font-mono">{shown.shipIds.join(', ')}</span>
      </span>
    ),
    shown.asOf && (
      <span key="as-of" className="-my-1 inline-flex items-center gap-0.5">
        기준일 {formatDay(shown.asOf)}
        <TermInfo term="asOf" />
      </span>
    ),
    shown.effectiveOn && <span key="effective">적용 시작 {formatDay(shown.effectiveOn)}</span>,
  ].filter(Boolean)
  return (
    <div className="border-b border-border px-4 py-3">
      {/* 제목 | 분석 조건(설계 승인 · 적용 시작일 · 변경 원인 · 확정일)을 한 줄에: 모니터처럼 넓으면 머리가 한 줄 줄고, 좁으면
          조건 묶음이 제목 아래로 내려간다. 휴대폰은 조건을 한 줄 요약으로 접는다 */}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{shown.title ?? '설계변경'}</h2>
          {meta.length > 0 && (
            <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-foreground-secondary">
              {meta.map((item, i) => (
                <Fragment key={i}>
                  {i > 0 && <span aria-hidden>·</span>}
                  {item}
                </Fragment>
              ))}
            </p>
          )}
        </div>
        <button
          type="button"
          className="flex min-h-11 w-full items-center justify-between gap-3 rounded-sm border border-border px-3 py-2 text-left text-sm sm:hidden"
          aria-expanded={conditionsOpen}
          aria-controls="ecn-conditions"
          onClick={() => setConditionsOpen((open) => !open)}
          data-testid="ecn-conditions-toggle"
        >
          <span className="min-w-0 text-foreground-secondary">{conditionSummary(draft)}</span>
          <span className="flex shrink-0 items-center gap-1 font-medium text-primary">
            {conditionsOpen ? '접기' : editable ? '조건 바꾸기' : '조건 보기'}
            <ChevronDown aria-hidden className={cn('size-4 transition-transform', conditionsOpen && 'rotate-180')} />
          </span>
        </button>
        <div
          id="ecn-conditions"
          className={cn('flex-wrap items-center gap-x-4 gap-y-2 text-sm', conditionsOpen ? 'flex' : 'hidden sm:flex')}
          data-testid="ecn-design"
        >
          {/* 확정일: 휴대폰은 펼친 조건의 맨 앞, 넓으면 맨 오른쪽(제목 줄 끝 — 가장 자주 바꾸는 칸) */}
          <Field id={`${ids}-confirm`} label="확정일" term="confirmOn" className="sm:order-last">
            <Input
              id={`${ids}-confirm`}
              type="date"
              value={draft.confirmOn ?? draft.asOf ?? ''}
              min={draft.asOf ?? undefined}
              disabled={!editable}
              onChange={(event) => onConfirmOn(event.target.value || null)}
              className="h-9 w-auto rounded-sm tabular-nums md:text-sm"
            />
          </Field>
          <Field id={`${ids}-design`} label="설계 승인" term="designStatus">
            <NativeSelect
              id={`${ids}-design`}
              aria-label="설계 승인 상태"
              className="w-auto min-w-32"
              value={draft.designStatus ?? 'unknown'}
              disabled={!editable}
              onChange={(event) => onDesignStatus(event.target.value as DesignStatus)}
            >
              {DESIGN_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {DESIGN_STATUS_NAMES[status]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={`${ids}-effective`} label="적용 시작일" term="effectiveOn">
            <Input
              id={`${ids}-effective`}
              type="date"
              value={draft.effectiveOn ?? ''}
              disabled={!editable}
              onChange={(event) => onEffectiveOn(event.target.value || null)}
              className="h-9 w-auto rounded-sm tabular-nums md:text-sm"
            />
          </Field>
          <Field id={`${ids}-cause`} label="변경 원인" term="cause">
            <NativeSelect
              id={`${ids}-cause`}
              aria-label="변경 원인"
              className="w-auto min-w-32"
              value={draft.cause ?? ''}
              disabled={!editable}
              onChange={(event) => onCause((event.target.value || null) as ChangeCause | null)}
            >
              <option value="">미입력</option>
              {CHANGE_CAUSES.map((cause) => (
                <option key={cause} value={cause}>
                  {CHANGE_CAUSE_NAMES[cause]}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
      </div>
      {lockNote && (
        <p className="mt-1.5 flex items-center justify-end gap-1 text-sm text-foreground-secondary" data-testid="conditions-locked">
          <Lock aria-hidden className="size-3.5 shrink-0" />
          {lockNote}
        </p>
      )}
      <CauseNote cause={draft.cause} />
      {verdict && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <VerdictBand
            level={verdict.level}
            reasons={verdict.reasons}
            info={<TermInfo term="verdict" />}
            className="flex-1 basis-72"
          />
          {actions && <div className="ml-auto shrink-0">{actions}</div>}
        </div>
      )}
    </div>
  )
}
