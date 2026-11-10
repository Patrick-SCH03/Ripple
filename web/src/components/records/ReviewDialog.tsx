// 검토 요청 확인 창(DESIGN.md 13절): 무엇을 올리는지(개정·판정·핵심 수치) 보여 주고 한 번 더 묻는다.
// 지금 화면의 분석이 아직 기록되지 않았으면 '기록하고 검토 요청' — 새 개정으로 기록한 뒤 바로 검토를 요청한다. 왼쪽 '닫기'.
// 검토는 결재선(docs/records.md(기록·결재) 14절)으로 올라간다 — 단계 수는 요청할 때 고정. 결재선·단계당 근무일은
// 분석 응답의 결재 계획(approval_plan.line·days_per_step_low·days_per_step) 그대로 쓴다(화면 상수 없음).
// 변경 원인이 없으면 요청하지 않는다(결재자가 비용 부담 판단 근거). 더 저렴한 권고 대안이 있으면 함께 보이고, 담당자 의견(선택)은
// 검토 요청 감사 줄의 사유로 남는다.
import { useState, type ReactNode } from 'react'
import type { AnalysisResult } from '@/api/client'
import { GlanceTiles, type GlanceTile } from '@/components/common/GlanceTiles'
import { SegmentText } from '@/components/common/SegmentText'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { useAlternatives } from '@/components/detail/alternatives/useAlternatives'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { REQUEST_ALT, mayHaveAlternatives, recommendationHeadline } from '@/lib/alternatives'
import { useReturnFocus } from '@/lib/focus'
import { lineNames, lineSummary, submitLine } from '@/lib/approval'
import { causeName } from '@/lib/request'
import { assumedPlan } from '@/lib/revisions'
import { ownerSummary } from '@/lib/stateBasis'
import { keyNumbers } from '@/lib/summary'

export interface ReviewAsk {
  /** 먼저 새 개정으로 기록하는가. */
  records: boolean
  /** 검토를 요청할 개정 번호(기록하면 새 번호). */
  revision: number
}

interface Props {
  ask: ReviewAsk | null
  /** 창을 열 때 고정한 분석(올릴 분석). */
  result: AnalysisResult
  /** 오늘(KST): 현장 상태 확인 필요 수를 상세 카드와 같은 날로 센다. */
  today: string
  /** 연 뒤 화면의 분석이나 결재 상태가 바뀌었다 — 확인을 막고 다시 열게 한다. */
  changed: boolean
  busy: boolean
  /** 요청한 사람은 그 검토를 직접 결정할 수 없다(로그인 모드). */
  selfDecisionNote: boolean
  serverError: string | null
  onOpenChange: (open: boolean) => void
  /** reason = 담당자 의견(앞뒤 공백 뺀 글, 없으면 빈 글). */
  onConfirm: (reason: string) => void
}

export function ReviewDialog(props: Props) {
  const open = props.ask !== null
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={props.onOpenChange}>
      <DialogContent className="sm:max-w-xl" onCloseAutoFocus={returnFocus} data-testid="review-dialog">
        {/* 창을 열 때마다 의견 칸을 비운다 */}
        {props.ask && <ReviewForm key={`${props.ask.revision}:${props.result.analysis_id}`} {...props} ask={props.ask} />}
      </DialogContent>
    </Dialog>
  )
}

/** 요약 표 한 줄: 이름(왼쪽 고정 폭) · 값. */
function Row({ label, testId, className, children }: { label: string; testId?: string; className?: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 px-3 py-2" data-testid={testId}>
      <dt className="w-24 shrink-0 text-foreground-secondary">{label}</dt>
      <dd className={className ? `min-w-0 ${className}` : 'min-w-0'}>{children}</dd>
    </div>
  )
}

/** 권고 대안 한 줄: 요청안보다 저렴한 권고가 있을 때만(대안 탭과 같은 계산 기억 — 끝나지 않았으면 없음). */
function useCheaper(result: AnalysisResult): string | null {
  const loaded = useAlternatives(result, mayHaveAlternatives(result.request))
  if (!loaded || 'error' in loaded) return null
  const rec = loaded.data.recommendation
  const headline = recommendationHeadline(loaded.data)
  if (!rec || rec.alt_id === REQUEST_ALT || !headline) return null
  return `${headline.title} · ${headline.detail}`
}

function ReviewForm({
  ask,
  result,
  today,
  changed,
  busy,
  selfDecisionNote,
  serverError,
  onConfirm,
}: Props & { ask: ReviewAsk }) {
  const [reason, setReason] = useState('')
  const cheaper = useCheaper(result)
  const label = ask.records ? '기록하고 검토 요청' : '검토 요청'
  const cards = keyNumbers(result)
  const total = cards.find((card) => card.id === 'total')
  const deadline = cards.find((card) => card.id === 'deadline')
  const glance: GlanceTile[] = [
    ...(total ? [{ id: 'total', label: total.label, value: total.value }] : []),
    ...(deadline ? [{ id: 'deadline', label: deadline.label, value: deadline.value, line: deadline.detail, tone: deadline.tone }] : []),
  ]
  const holds = assumedPlan(result)
  const line = lineSummary(result.approval_plan)
  const names = lineNames(result.approval_plan)
  const noCause = !result.request.change.cause
  const submit = submitLine(result.approval_plan, false)
  // 계산에 쓴 발주 단계·공정 실적 중 확인할 것(구매·생산관리 몫 — 상세 카드와 같은 오늘 기준)
  const owners = ownerSummary(result.state_basis ?? [], today)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (!noCause) onConfirm(reason.trim())
      }}
      className="space-y-4"
    >
      <DialogHeader>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <DialogTitle>
            개정 {ask.revision} {label}
          </DialogTitle>
          <VerdictBadge level={result.verdict.level} />
        </div>
        <DialogDescription>
          {ask.records
            ? '지금 화면의 분석을 새 개정으로 기록 → 결재선에 검토 요청 · 기록한 개정은 수정 불가'
            : '이 개정의 분석으로 결재선에 검토 요청'}
        </DialogDescription>
      </DialogHeader>
      {/* 무엇을 올리는지 한눈에: 큰 숫자 둘(총변경비용 · 결정 기한) — 범위는 아래 표, 판정은 제목 옆 배지 */}
      <GlanceTiles testId="review-glance" tiles={glance} />
      <dl className="divide-y divide-border rounded-sm border border-border text-sm" data-testid="review-summary">
        <Row label="설계변경">
          {result.request.change.ecn_id} · {result.request.change.title}
        </Row>
        <Row label="변경 원인" testId="review-cause" className={noCause ? 'text-danger' : undefined}>
          {causeName(result.request.change.cause)}
          {noCause && " — 결재자가 비용 부담 판단 근거 · 닫고 위 '변경 원인'에서 선택"}
        </Row>
        {submit && submit.tone !== 'none' && (
          <Row
            label="올릴 기한"
            testId="review-submit-by"
            className={submit.tone === 'late' ? 'font-medium text-danger' : submit.tone === 'caution' ? 'font-medium text-warning' : undefined}
          >
            <SegmentText text={submit.text.replace(/^결재 올릴 기한 /, '')} />
          </Row>
        )}
        {cheaper && (
          <Row label="권고 대안" testId="review-cheaper">
            <SegmentText text={cheaper} />
          </Row>
        )}
        {holds && (
          <Row label="가정 계산" testId="review-assumed">
            <SegmentText text={holds} />
          </Row>
        )}
        {line && (
          <Row label="결재선" testId="review-line">
            <SegmentText text={line} />
          </Row>
        )}
        {total?.detail && (
          <Row label="금액 범위" className="tabular-nums">
            {total.detail}
          </Row>
        )}
        {owners && (
          <Row label="현장 상태" testId="review-states">
            <SegmentText text={`확인 필요 ${owners.count} · ${owners.text}`} />
            <span className="text-foreground-secondary">
              {' · '}
              <span className="whitespace-nowrap">결재 중 해당 부서 확인</span>
            </span>
          </Row>
        )}
      </dl>
      <label className="block space-y-1.5 text-sm">
        <span className="font-semibold">담당자 의견(선택)</span>
        <Textarea
          value={reason}
          maxLength={500}
          rows={2}
          onChange={(event) => setReason(event.target.value)}
          placeholder={
            cheaper ? '예: 선급 요구라 요청안대로 · 권고 대안은 강도 검토 필요' : '예: 선급 요구 반영 · 협력사 납기 확인 완료'
          }
          data-testid="review-reason"
        />
      </label>
      {selfDecisionNote && (
        <p className="text-sm text-foreground-secondary">
          요청한 검토는 결재선의 {names ? `${names}이` : '결재자가'} 차례로 승인·반려·보류(팀장은 다른 단계 전결 가능)
        </p>
      )}
      {changed && (
        <p role="alert" className="rounded-sm border border-warning/50 px-3 py-2 text-sm text-warning" data-testid="review-changed">
          창을 연 뒤 분석·결재 상태 바뀜 · 닫고 다시 확인
        </p>
      )}
      {serverError && (
        <p role="alert" className="rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">
          {serverError}
        </p>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            닫기
          </Button>
        </DialogClose>
        <Button type="submit" disabled={busy || changed || noCause} data-testid="review-submit">
          {busy ? '요청하는 중…' : label}
        </Button>
      </DialogFooter>
    </form>
  )
}
