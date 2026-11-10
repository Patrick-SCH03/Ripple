// 결재 띠(상세 머리 아래, DESIGN.md 13절): 상태 칩 · 개정·기록한 사람·시각 · 알아야 할 한 줄 · 할 수 있는 행동.
// 못 하는 행동은 숨기지 않고 흐린 단추 + 이유 한 줄(역할 밖의 행동은 아예 없음). 결정은 대화상자를 거친다.
// 화면의 분석과 결재 대상이 같은 ECN일 때만 그린다(다른 ECN을 고른 직후 분석이 오기 전에는 숨김). 결정 대화상자는 열 때의
// 대상(버전·개정·기록·검토 순번)을 고정해 보내고, 그사이 상태가 바뀌어 거절되면 닫고 다시 확인하게 한다.
// 가운데 줄·단추·안내 줄은 approvalBand/의 부품, 팀장이 검토·보류 중인 개정을 볼 때의 결정 도우미는 brief/.
import { useState } from 'react'
import type { AnalysisResult, ChecklistItem, EcnAction, Me, VerdictLevel } from '@/api/client'
import { can } from '@/lib/account'
import { decideAs, decisionNote } from '@/lib/approval'
import { availableActions, flowNotice } from '@/lib/records'
import { reportPath } from '@/lib/report'
import {
  assumedPlan,
  reviewKey,
  reviewStale,
  revisionFacts,
  revisionGlance,
  sameAsRecorded,
  type Fact,
  type GlanceFact,
} from '@/lib/revisions'
import { targetOf, type ActionTarget, type RecordsState } from '@/state/useRecords'
import { ApprovalActions } from './approvalBand/ApprovalActions'
import { ApprovalMeta } from './approvalBand/ApprovalMeta'
import { ApprovalNotes } from './approvalBand/ApprovalNotes'
import { DecisionBriefPanel } from './brief/DecisionBriefPanel'
import { groupReasons } from './approvalBand/reasons'
import { DecisionDialog } from './DecisionDialog'
import { OutcomeLine } from './OutcomeLine'
import { ReviewDialog, type ReviewAsk } from './ReviewDialog'
import { StateChip } from './StateChip'

interface Props {
  me: Me
  records: RecordsState
  result: AnalysisResult | null
  /** 화면 결과가 지금 초안과 같고 계산이 끝났는가. */
  resultReady: boolean
  /** 지금 작업 공간의 지도 ID. */
  snapshotId: string | null
  loginMode: boolean
  /** 그 개정의 기록된 분석(요청)을 지금 지도에서 다시 연다. */
  onOpenRecorded?: (recordId: string) => void
  /** 오늘(KST): 검토 요청 창의 현장 상태 줄이 상세의 '계산에 쓴 현장 상태'와 같은 날로 센다. */
  today: string
}

interface Open {
  action: EcnAction
  target: ActionTarget
  /** 열 때의 확인 목록(그사이 새 개정이 와도 이 대상의 목록으로 묻는다 — 보내면 서버가 대상을 대조한다). */
  checklist: ChecklistItem[]
  /** 결정할 개정(최신 개정)의 요약(기록 본문 값). */
  facts: Fact[]
  /** 맨 위 큰 숫자 칸(총변경비용 · 결정 기한)과 판정 — 같은 개정 요약에서(없으면 표만). */
  glance: GlanceFact[]
  verdict: VerdictLevel | null
  /** 결재선 안내(지금 단계·다음 단계·전결) — 열 때 고정. */
  note: string | null
}

/**
 * 검토 요청 확인 창을 열 때 고정하는 것: 보여 준 분석(올릴 분석) · 그때의 결재 상태 판 · 대상 개정.
 * 그사이 화면의 분석이나 상태 판이 바뀌면 확인을 막고 다시 열게 한다(reviewStale).
 */
interface ReviewOpen extends ReviewAsk {
  target: ActionTarget | null
  result: AnalysisResult
  key: string
  version: number
}

export function ApprovalBand({
  me,
  records,
  result,
  resultReady,
  snapshotId,
  loginMode,
  onOpenRecorded,
  today,
}: Props) {
  const [open, setOpen] = useState<Open | null>(null)
  const [review, setReview] = useState<ReviewOpen | null>(null)
  const { detail, busy, error } = records
  if (!result || !records.detailReady || records.ecnId !== result.request.change.ecn_id) return null
  const status = detail?.status ?? null
  const latest = detail?.revisions.at(-1) ?? null
  const input = {
    me,
    status,
    resultReady,
    shownMatches: sameAsRecorded(latest, result, {
      design_status: detail?.latest_design_status,
      effectivity: detail?.latest_effectivity,
      cause: detail?.latest_cause,
    }),
    sameMap: status !== null && status.snapshot_id === snapshotId,
    sameVersion: detail?.same_version ?? true,
    loginMode,
    plan: detail?.approval_plan ?? null,
  }
  const actions = availableActions(input)
  const notice = flowNotice(input)
  const blocked = groupReasons(actions)
  // 보류를 넣은 분석은 가정 계산이다 — 그대로 기록·검토 요청하면 그 가정이 개정에 함께 남는다
  const assumed = !input.shownMatches ? assumedPlan(result) : null
  // 강조는 다음 단계 하나: 결정(승인) · 무비용 담당자 처리 · 검토 요청. 검토 요청이 없을 때만 '기록만 남기기'를 강조하되,
  // 결정을 기다리는 동안 새 개정은 진행 중 검토를 끝내므로 강조하지 않는다
  const reviewing = status?.state === 'in_review' || status?.state === 'on_hold'
  const canReview = actions.some((view) => view.action === 'request_review')
  const primary = (action: EcnAction) =>
    action === 'approve' ||
    action === 'settle' ||
    (action === 'request_review' && !actions.some((view) => view.action === 'settle')) ||
    (action === 'record' && !reviewing && !canReview)
  const message =
    error?.code === 'ecn_changed'
      ? '다른 사람이 먼저 변경(새 개정·검토·결정) · 바뀐 내용 다시 불러옴 · 확인 후 다시 진행'
      : (error?.message ?? null)
  // 기록된 분석 열기 = 그 요청을 지금 지도·지금 판으로 다시 계산 → 같은 지도·같은 판일 때만 기록과 같은 분석이 나온다.
  // 계산 판이 바뀐 개정은 저장된 기록 그대로(리포트)로 보게 한다.
  const recordedId =
    status !== null && !input.shownMatches && input.sameMap && input.sameVersion ? status.record_id : null
  const storedReport =
    status !== null && latest !== null && !input.sameVersion ? reportPath(status.ecn_id, latest.revision) : null
  // 실적: 실행을 시작했거나 끝낸 설계변경만. 예측 = 승인한 개정의 총변경비용
  const executed = status?.state === 'in_progress' || status?.state === 'closed'
  const approved = executed ? detail?.revisions.find((r) => r.revision === status?.approved_revision) : undefined
  const run = (action: EcnAction) => {
    const view = actions.find((a) => a.action === action)
    if (action === 'record') void records.save(result)
    else if (action === 'request_review') {
      records.clearError()
      const recordsFirst = view?.records ?? false
      setReview({
        records: recordsFirst,
        revision: recordsFirst ? (latest?.revision ?? 0) + 1 : (latest?.revision ?? 1),
        target: !recordsFirst && detail ? targetOf(detail) : null,
        result,
        key: reviewKey(result),
        version: status?.version ?? 0,
      })
    } else if (view?.dialog && detail) {
      records.clearError()
      // 결정 대상은 늘 최신 개정이라(status.revision) 변경 원인도 최신 개정의 것. 후행 설치 가정은 화면의 분석이 그 개정일
      // 때 그 요청에서(분석 ID에 들어가 같은 기록이면 같다)
      const target = targetOf(detail)
      const summary = detail.revisions.find((r) => r.revision === target.revision)
      const onBoard = input.shownMatches ? result.request.outfit_on_board : undefined
      setOpen({
        action,
        target,
        checklist: [...detail.checklist],
        facts: summary ? revisionFacts(summary, detail.latest_cause, onBoard) : [],
        glance: summary ? revisionGlance(summary, today) : [],
        verdict: summary?.verdict ?? null,
        note: decisionNote(action, detail.status, decideAs(me, detail.status, loginMode)),
      })
    } else void records.act(action)
  }
  const submit = async (reason: string, acknowledged: string[]) => {
    if (!open) return
    const outcome = await records.act(open.action, { reason, acknowledged }, open.target)
    // 성공이면 닫고, 그사이 상태가 바뀌었으면 닫아 띠에 이유를 보인다(새 상태로 다시 확인해 결정하게)
    if (outcome !== 'failed') setOpen(null)
  }
  const reviewChanged =
    review !== null && reviewStale(review, { key: reviewKey(result), version: status?.version ?? 0 })
  const confirmReview = async (reason: string) => {
    if (!review || reviewChanged) return
    // 기록부터 하면 창에 보여 준 그 분석을 창을 열 때의 상태 판으로 보낸다(그사이 바뀌었으면 서버가 거절한다)
    const outcome = await records.requestReview(
      review.records ? review.result : null,
      review.target ?? undefined,
      review.version,
      reason,
    )
    if (outcome !== 'failed') setReview(null)
  }
  return (
    <section
      aria-label="결재"
      className="border-b border-border px-4 py-2.5"
      data-testid="approval-band"
      data-ecn={result.request.change.ecn_id}
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <span className="mt-1 flex">
          <StateChip state={status?.state ?? 'requested'} size="md" />
        </span>
        <ApprovalMeta me={me} status={status} latest={latest} audit={detail?.audit ?? []} />
        {actions.length > 0 && (
          <ApprovalActions actions={actions} primary={primary} busy={busy} syncing={records.syncing} onRun={run} />
        )}
      </div>
      {(notice || assumed || blocked.length > 0) && (
        <ApprovalNotes
          assumed={assumed}
          notice={notice}
          recordedId={recordedId}
          onOpenRecorded={onOpenRecorded}
          storedReport={storedReport}
          blocked={blocked}
        />
      )}
      {/* 결정 도우미: 팀장 + 검토·보류 중일 때만(불러오기 실패·지연이 단추를 막지 않음) */}
      <DecisionBriefPanel me={me} detail={detail} result={result} shownMatches={input.shownMatches} today={today} />
      {executed && status && (
        <OutcomeLine
          ecnId={status.ecn_id}
          version={status.version}
          predicted={approved?.total ?? null}
          canEnter={can(me, 'record')}
        />
      )}
      {message && open === null && review === null && (
        <p role="alert" className="mt-2 rounded-sm border border-danger/40 px-3 py-1.5 text-sm text-danger">
          {message}
        </p>
      )}
      <DecisionDialog
        action={open?.action ?? null}
        revision={open?.target.revision ?? 0}
        formKey={open ? `${open.action}:${open.target.record_id}:${open.target.version}` : ''}
        facts={open?.facts ?? []}
        glance={open?.glance ?? []}
        verdict={open?.verdict ?? null}
        checklist={open?.checklist ?? []}
        note={open?.note ?? null}
        busy={busy !== null}
        serverError={open !== null ? message : null}
        onOpenChange={(next) => !next && setOpen(null)}
        onSubmit={(reason, acknowledged) => void submit(reason, acknowledged)}
      />
      <ReviewDialog
        ask={review}
        today={today}
        result={review?.result ?? result}
        changed={reviewChanged}
        busy={busy !== null}
        selfDecisionNote={loginMode}
        serverError={review !== null ? message : null}
        onOpenChange={(next) => !next && setReview(null)}
        onConfirm={(reason) => void confirmReview(reason)}
      />
    </section>
  )
}
