// 기록·승인 상태(docs/records.md): ECN 목록의 상태(useEcnList) · 고른 ECN의 상세(useEcnDetail) · 기록 저장 · 행동.
// 작업 공간마다 새로 만든다(Workbench와 같은 수명). 저장·행동은 작업 공간 토큰을 싣는 묶인 요청이고, 서버가 그 세대로
// 다시 계산하고 지도를 대조한다. 오류는 '어느 ECN의 것인지'와 함께 두고 렌더할 때 지금 고른 ECN의 것만 쓴다
// (고른 ECN이 바뀐 뒤 늦게 온 이전 ECN의 오류가 섞이지 않게).
import { useCallback, useRef, useState } from 'react'
import {
  ApiError,
  api,
  type AnalysisResult,
  type EcnAction,
  type EcnDetail,
  type EcnListItem,
  type EcnStatus,
  type NoticeLog,
} from '@/api/client'
import { effectivityKey } from '@/lib/revisions'
import { listedOf, useEcnDetail, type RecordFailure } from './useEcnDetail'
import { useEcnList } from './useEcnList'


/** 행동을 보낼 대상: 화면이 본 상태(버전·개정·기록·검토 순번). 서버가 지금과 다르면 거절한다. */
export interface ActionTarget {
  version: number
  revision: number
  record_id: string
  review_seq: number | null
}

/** 행동 결과: changed = 그사이 상태가 바뀌어 거절됨(다시 확인해야 함). */
export type ActOutcome = 'ok' | 'changed' | 'failed'

export interface RecordsState {
  /** 지금 따라가는 ECN(목록에서 고른 것). */
  ecnId: string | null
  items: EcnListItem[]
  /** 목록을 한 번이라도 읽었는가. */
  ready: boolean
  /**
   * 목록 읽기가 실패 중이면 그 장애의 순번(성공 뒤 다시 실패할 때마다 1씩), 성공하면 null. 결재 대기·내가 올린
   * 설계변경이 빠져 보일 수 있어 화면이 알린다(닫은 장애는 다시 보이지 않고, 회복 뒤 새 장애는 다시 보인다).
   */
  listFailure: number | null
  /** 고른 ECN의 상세. 기록이 없으면 null. */
  detail: EcnDetail | null
  /** detail이 지금 고른 ECN의 것인가(읽는 중이면 false). */
  detailReady: boolean
  /** 진행 중인 행동(단추를 막고 '…하는 중' 표시). */
  busy: EcnAction | null
  /** 행동 뒤 상세를 다시 읽는 중(옛 상태로 단추를 다시 누르지 않게 막는다). */
  syncing: boolean
  error: ApiError | null
  save: (result: AnalysisResult) => Promise<boolean>
  act: (action: EcnAction, extra?: { reason?: string; acknowledged?: string[] }, target?: ActionTarget) => Promise<ActOutcome>
  /**
   * 검토 요청. result를 주면 먼저 그 분석을 새 개정으로 기록하고, 저장 응답의 상태(버전·개정)로 바로 검토를 요청한다
   * (기록만 되고 요청이 거절되면 기록은 남는다 — 오류로 알린다). result가 null이면 target(최신 개정)의 검토만 요청한다.
   * expectedVersion = 확인 창을 열 때 본 상태 판(그사이 바뀌었으면 서버가 저장을 거절한다).
   * reason = 담당자 의견(선택) — 검토 요청 감사 줄의 사유로 남아 결재자의 이력·리포트에 보인다.
   */
  requestReview: (
    result: AnalysisResult | null,
    target?: ActionTarget,
    expectedVersion?: number,
    reason?: string,
  ) => Promise<ActOutcome>
  /**
   * 1.28.0 통보 기록(보냄·수령 확인·회신)을 고른 ECN의 최신 개정에 남긴다. 상태·버전은 그대로라 결재 흐름을 막지 않는다.
   * 실패면 이유 문장, 성공이면 null(상세를 다시 읽어 이력·카드에 보인다).
   */
  notice: (log: NoticeLog) => Promise<string | null>
  clearError: () => void
  reload: () => void
}

/** 저장 요청 ID: 같은 분석·같은 기대 버전을 연결 실패로 다시 보낼 때만 같은 ID(서버가 처음 결과를 돌려준다). */
interface Pending {
  key: string
  id: string
}

/** 행동 하나를 보낸다(busy·오류 표시는 부르는 쪽). */
async function sendAction(
  id: string,
  action: EcnAction,
  extra: { reason?: string; acknowledged?: string[] },
  sent: ActionTarget,
): Promise<void> {
  await api.act(id, {
    action,
    expected_version: sent.version,
    revision: sent.revision,
    record_id: sent.record_id,
    review_seq: sent.review_seq,
    reason: extra.reason?.trim() ? extra.reason.trim() : null,
    acknowledged: extra.acknowledged ?? [],
  })
}

export function targetOf(detail: EcnDetail): ActionTarget {
  const { status } = detail
  return {
    version: status.version,
    revision: status.revision,
    record_id: status.record_id,
    review_seq: status.review?.seq ?? null,
  }
}

export function useRecords(ecnId: string | null): RecordsState {
  const [busy, setBusy] = useState<EcnAction | null>(null)
  const [failure, setFailure] = useState<RecordFailure | null>(null)
  const pending = useRef<Pending | null>(null)
  const { items, ready, listFailure, reloadList } = useEcnList()
  // 목록에 기록이 없는 ECN은 상세를 읽지 않는다(기록 없음 = 404 — 콘솔 오류만 남음)
  const listed = listedOf(ecnId, items, ready, listFailure)
  const { loaded, detail, detailVersion, reloadDetail } = useEcnDetail(ecnId, listed, busy !== null, setFailure, reloadList)

  const refresh = useCallback(() => {
    reloadList()
    reloadDetail()
  }, [reloadList, reloadDetail])

  const fail = useCallback(
    (caught: unknown, id: string): ActOutcome => {
      const error = caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
      setFailure({ id, error })
      if (error.code === 'ecn_changed') {
        refresh() // 그사이 바뀐 상태를 다시 읽어 보여 준다
        return 'changed'
      }
      return 'failed'
    },
    [refresh],
  )

  /** 분석을 개정으로 저장하고 저장된 상태를 돌려준다(실패는 던진다). busy·오류 표시는 부르는 쪽이 한다. */
  const persist = useCallback(
    async (result: AnalysisResult, expectedVersion?: number): Promise<EcnStatus> => {
      const id = result.request.change.ecn_id
      const expected = expectedVersion ?? (loaded?.id === id && loaded.detail ? loaded.detail.status.version : 0)
      const change = result.request.change
      const key = [
        result.analysis_id,
        change.title,
        change.intent ?? '',
        change.design_status ?? 'unknown',
        effectivityKey(change.effectivity),
        change.cause ?? '',
        expected,
      ].join(':')
      const requestId = pending.current?.key === key ? pending.current.id : crypto.randomUUID()
      pending.current = { key, id: requestId }
      try {
        const saved = await api.saveRecord({
          request: result.request,
          analysis_id: result.analysis_id,
          request_id: requestId,
          expected_version: expected,
        })
        pending.current = null
        return saved.status
      } catch (caught) {
        // 연결 실패만 같은 ID로 다시 보낸다(서버가 받았는지 모르므로). 거절이면 다음은 새 요청이다
        if (!(caught instanceof ApiError && caught.status === 0)) pending.current = null
        throw caught
      }
    },
    [loaded],
  )

  const save = useCallback(
    async (result: AnalysisResult) => {
      setBusy('record')
      setFailure(null)
      try {
        await persist(result)
        refresh()
        return true
      } catch (caught) {
        fail(caught, result.request.change.ecn_id)
        return false
      } finally {
        setBusy(null)
      }
    },
    [persist, fail, refresh],
  )

  const act = useCallback(
    async (
      action: EcnAction,
      extra: { reason?: string; acknowledged?: string[] } = {},
      target?: ActionTarget,
    ): Promise<ActOutcome> => {
      if (!detail) return 'failed'
      const id = detail.status.ecn_id
      // 대상을 받았으면(결정 대화상자를 열 때 고정) 그대로 보낸다: 그사이 새 개정·검토가 생겼으면 서버가 거절한다
      setBusy(action)
      setFailure(null)
      try {
        await sendAction(id, action, extra, target ?? targetOf(detail))
        refresh()
        return 'ok'
      } catch (caught) {
        return fail(caught, id)
      } finally {
        setBusy(null)
      }
    },
    [detail, fail, refresh],
  )

  const requestReview = useCallback(
    async (
      result: AnalysisResult | null,
      target?: ActionTarget,
      expectedVersion?: number,
      reason?: string,
    ): Promise<ActOutcome> => {
      const id = result?.request.change.ecn_id ?? detail?.status.ecn_id
      let sent = target ?? (detail ? targetOf(detail) : null)
      if (id === undefined || (result === null && sent === null)) return 'failed'
      setBusy('request_review')
      setFailure(null)
      let recorded: number | null = null
      try {
        if (result !== null) {
          const status = await persist(result, expectedVersion)
          recorded = status.revision
          sent = { version: status.version, revision: status.revision, record_id: status.record_id, review_seq: null }
        }
        if (sent === null) return 'failed'
        await sendAction(id, 'request_review', { reason }, sent)
        refresh()
        return 'ok'
      } catch (caught) {
        if (recorded === null) return fail(caught, id)
        // 기록은 남고 검토 요청만 거절됨: 새 개정을 다시 읽어 보이고, 무엇이 남았는지 함께 알린다
        refresh()
        const error = caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
        setFailure({
          id,
          error: new ApiError(`개정 ${recorded}로 기록됨 · 검토 요청 실패 — ${error.message}`, error.status, error.problems),
        })
        return 'failed'
      } finally {
        setBusy(null)
      }
    },
    [detail, persist, fail, refresh],
  )

  const notice = useCallback(
    async (log: NoticeLog): Promise<string | null> => {
      if (!detail) return '기록 먼저 필요 — 통보는 기록한 개정에 붙여 남김'
      const id = detail.status.ecn_id
      setBusy('notice')
      try {
        await api.notice(id, { record_id: detail.status.record_id, notice: log })
        reloadDetail()
        return null
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === 'ecn_changed') refresh()
        return caught instanceof ApiError ? caught.message : '연결 끊김'
      } finally {
        setBusy(null)
      }
    },
    [detail, refresh, reloadDetail],
  )

  return {
    ecnId,
    items,
    ready,
    listFailure,
    detail,
    // 지금 고른 ECN의 마지막 읽기가 끝났는가(행동 뒤 다시 읽는 동안은 이전 상세를 그대로 보인다)
    detailReady: ecnId === null || loaded?.id === ecnId,
    busy,
    syncing: loaded !== null && loaded.id === ecnId && loaded.version !== detailVersion,
    error: failure && failure.id === ecnId ? failure.error : null,
    save,
    act,
    requestReview,
    notice,
    clearError: () => setFailure(null),
    reload: refresh,
  }
}
