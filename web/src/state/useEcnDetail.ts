// 고른 ECN의 상세(개정·감사·확인 목록, docs/records.md(기록·결재)). 상세·오류는 '어느 ECN의 것인지'와 함께 두고 렌더할 때
// 지금 고른 ECN의 것만 쓴다(고른 ECN이 바뀐 뒤 늦게 온 이전 ECN의 상세가 섞이지 않게).
// 결재 상태 목록에 없는 ECN(기록 전)은 상세를 읽지 않는다(detailPlan — 기록 없음 404가 콘솔 오류로 남지 않게). 다만
// 기록·검토 직후 다시 읽으라고 한 ECN은 목록이 따라잡을 때까지 ECN별로 기억해 읽는다(다른 ECN을 열었다 돌아와도).
// 다른 사람의 결재(다른 브라우저)도 보이게: 창이 다시 보이거나 초점을 받을 때와 보이는 동안 일정 간격으로 목록을 다시 읽고,
// 고른 ECN의 상태 판이 바뀌었으면 상세를 다시 읽는다.
// 받은 콜백(onFailure·reloadList)은 효과 이벤트로 불러 효과의 의존성에 넣지 않는다: 부르는 쪽이 렌더마다 새 함수를 넘겨도
// 상세를 다시 읽거나 주기 확인을 다시 걸지 않는다(다시 읽는 때는 고른 ECN과 다시 읽기 버전만 정한다).
import { useCallback, useEffect, useEffectEvent, useRef, useState } from 'react'
import { ApiError, api, type EcnDetail, type EcnListItem } from '@/api/client'

/** 보이는 동안 다른 사람의 결재를 확인하는 간격. */
const RECORDS_POLL_MS = 20_000

/** 마지막으로 읽은 상세: 어느 ECN의, 몇 번째 다시 읽기의 것인지(기록이 없으면 detail = null). */
export interface Loaded {
  id: string
  version: number
  detail: EcnDetail | null
}

/** 어느 ECN에서 난 오류인지와 함께 둔다. */
export interface RecordFailure {
  id: string
  error: ApiError
}

/**
 * 결재 상태 목록(GET /api/ecns)으로 본 기록 여부: 목록을 아직 못 읽음(pending) · 목록에 있음(listed) · 없음(absent — 상세를
 * 읽으면 404) · 목록 읽기 실패(unknown — 상세를 읽어 본다).
 */
export type Listed = 'pending' | 'listed' | 'absent' | 'unknown'

export function listedOf(
  ecnId: string | null,
  items: readonly EcnListItem[],
  ready: boolean,
  listFailure: number | null,
): Listed {
  if (!ready) return 'pending'
  if (listFailure !== null) return 'unknown'
  return ecnId !== null && items.some((item) => item.status.ecn_id === ecnId) ? 'listed' : 'absent'
}

/**
 * 상세를 읽을까: 기록 목록에 없는 설계변경(기록 전 샘플·비서가 만든 분석)은 읽지 않는다 — 기록 없음은
 * 서버 계약대로 404라 브라우저 콘솔에 빨간 줄만 남긴다. 목록을 읽기 전이면 기다리고, 같은 설계변경을 다시 읽으라고 했으면
 * (reread — 기록·행동 직후, 다시 읽는 목록이 아직 옛것일 수 있음) 목록에 없어도 읽는다.
 */
export function detailPlan(listed: Listed, reread: boolean): 'wait' | 'skip' | 'fetch' {
  if (listed === 'pending') return 'wait'
  return listed === 'absent' && !reread ? 'skip' : 'fetch'
}

export interface EcnDetailState {
  loaded: Loaded | null
  /** 지금 고른 ECN의 상세(없거나 아직 읽지 않았으면 null). */
  detail: EcnDetail | null
  /** 다시 읽기 버전(loaded.version과 다르면 다시 읽는 중). */
  detailVersion: number
  reloadDetail: () => void
}

/**
 * listed = 결재 상태 목록으로 본 기록 여부(listedOf — 목록에 없으면 상세를 읽지 않는다).
 * busy = 행동이 진행 중인가(주기 확인이 끼어들지 않게). onFailure = 상세 읽기 오류(404 = 기록 없음은 빼고).
 * reloadList = 주기 확인 때 결재 상태 목록도 다시 읽는다. 두 콜백은 부를 때의 최신 것을 쓴다(안정한 함수일 필요 없음).
 */
export function useEcnDetail(
  ecnId: string | null,
  listed: Listed,
  busy: boolean,
  onFailure: (failure: RecordFailure) => void,
  reloadList: () => void,
): EcnDetailState {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [detailVersion, setDetailVersion] = useState(0)
  const reportFailure = useEffectEvent(onFailure)
  const refreshList = useEffectEvent(reloadList)
  // 주기 확인이 지금 상세의 상태 판과 비교하고, 행동 중에는 끼어들지 않게(렌더 밖에서만 읽는다)
  // 감사 줄 수도 본다: 통보 기록(1.28.0)은 상태 판을 올리지 않아 판만 보면 동료가 남긴 통보를 놓친다
  const known = useRef<{ id: string | null; version: number | null; lines: number | null; busy: boolean; listed: Listed }>({
    id: null,
    version: null,
    lines: null,
    busy: false,
    listed: 'pending',
  })
  // 마지막으로 정한 상세(읽었거나 기록 없음으로 둔 것)가 어느 ECN의 몇 번째 다시 읽기였나: 같은 ECN을 다시 읽으라고 한 것
  // (기록·행동 직후)을 가른다. 정해졌을 때만 바꾼다(엄격 모드에서 효과가 두 번 돌아도 다시 읽기를 잃지 않게)
  const settled = useRef<{ id: string; version: number } | null>(null)
  // 다시 읽으라고 한 설계변경(기록·검토 직후)을 ECN별로 기억한다: 다른 설계변경을 열었다가 목록을
  // 다시 읽기 전에 돌아와도 목록에 아직 없다는 이유로 '기록 전'으로 두지 않고 읽는다. 목록에 나타나면(목록이 따라잡음)
  // 또는 상세가 404(기록 없음)면 뺀다 — 기록 없는 설계변경의 404를 되풀이하지 않게
  const rereads = useRef(new Set<string>())

  useEffect(() => {
    if (ecnId === null) return
    if (settled.current?.id === ecnId && settled.current.version !== detailVersion) rereads.current.add(ecnId)
    if (listed === 'listed') rereads.current.delete(ecnId)
    const plan = detailPlan(listed, rereads.current.has(ecnId))
    if (plan === 'wait') return
    const settle = (found: EcnDetail | null) => {
      settled.current = { id: ecnId, version: detailVersion }
      setLoaded({ id: ecnId, version: detailVersion, detail: found })
    }
    if (plan === 'skip') {
      settle(null) // 기록 목록에 없음 = 기록 없음(읽으면 404)
      return
    }
    let live = true
    api.ecn(ecnId).then(
      (found) => live && settle(found),
      (caught: unknown) => {
        if (!live) return
        if (caught instanceof ApiError && caught.status === 404) rereads.current.delete(ecnId)
        settle(null)
        if (caught instanceof ApiError && caught.status !== 404) reportFailure({ id: ecnId, error: caught })
      },
    )
    return () => {
      live = false
    }
  }, [ecnId, detailVersion, listed])

  const detail = loaded && loaded.id === ecnId ? loaded.detail : null

  useEffect(() => {
    known.current = {
      id: loaded && loaded.id === ecnId ? ecnId : null,
      version: detail ? detail.status.version : null,
      lines: detail ? detail.audit.length : null,
      busy,
      listed,
    }
  }, [loaded, ecnId, detail, busy, listed])

  // 다른 사람의 결재: 다시 보이거나 초점을 받을 때 + 보이는 동안 일정 간격
  useEffect(() => {
    let live = true
    const check = () => {
      if (document.visibilityState !== 'visible' || known.current.busy) return
      refreshList()
      if (ecnId === null || known.current.id !== ecnId) return
      const before = known.current.version
      const lines = known.current.lines
      // 기록이 없던 설계변경은 위에서 다시 읽은 목록에 나타나면 그때 읽는다(여기서 404를 되풀이하지 않게)
      if (detailPlan(known.current.listed, before !== null) !== 'fetch') return
      api.ecn(ecnId).then(
        (found) => {
          const changed = found.status.version !== before || found.audit.length !== lines
          if (live && !known.current.busy && known.current.id === ecnId && changed) {
            setDetailVersion((v) => v + 1)
          }
        },
        (caught: unknown) => {
          // 기록이 있던 ECN이 사라졌을 때만(없던 ECN의 404는 그대로)
          if (live && caught instanceof ApiError && caught.status === 404 && before !== null) {
            setDetailVersion((v) => v + 1)
          }
        },
      )
    }
    const timer = window.setInterval(check, RECORDS_POLL_MS)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => {
      live = false
      window.clearInterval(timer)
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
  }, [ecnId])

  const reloadDetail = useCallback(() => setDetailVersion((v) => v + 1), [])
  return { loaded, detail, detailVersion, reloadDetail }
}
