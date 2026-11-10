// 분석 세션: 샘플 · 요청 초안(JSON 글) · 표시 중인 분석 결과 · 선택 · 오류. 화면 배치와 상관없는 상태만 둔다.
// 화면 세대(lib/generation)는 사용자가 상세에 보일 분석을 바꿀 때마다 올려, 늦게 온 비서 응답이 덮지 않게 한다.
// 작업 공간(지도)마다 따로다: Workbench가 작업 공간 토큰을 key로 다시 그려 이 상태를 새로 만들고, 사라질 때 진행 중
// 분석을 멈춘다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  WORKSPACE_CHANGED,
  api,
  expectedWorkspace,
  type AnalysisRequest,
  type AnalysisResult,
  type Health,
  type Sample,
} from '@/api/client'
import { firstToOpen, isClosed } from '@/lib/ecnList'
import { ScreenGeneration } from '@/lib/generation'
import { LatestGate } from '@/lib/latest'
import { takeRerun } from '@/lib/rerun'
import {
  contextOf,
  parseRequest,
  reflectsRecord,
  resultState,
  type ChangeCause,
  type DesignStatus,
  type RequestContext,
  type ResultState,
} from '@/lib/request'
import { useDraftEdits } from './useDraftEdits'

export type { ResultState } from '@/lib/request'

/** 가정 계산(보류 적용·빼기, 대안으로 보기) 바로 전 결과: 새 결과와 나란히 '바뀐 점'을 보이고 되돌릴 때 쓴다. */
export interface Comparison {
  /** 무엇을 바꿨는지 한 줄(예: '발주 PO-1 5일 보류', '대안: 보강재 추가'). */
  label: string
  before: AnalysisResult
}

export interface AnalysisSession {
  health: Health | null
  samples: Sample[]
  /** 목록에서 고른(또는 표시 중인 결과의) ECN 번호. */
  chosen: string | null
  draft: string
  draftValid: boolean
  /** 확정일 고르기에 쓰는 초안 값. */
  draftContext: RequestContext
  result: AnalysisResult | null
  /** 표시 중인 결과가 답한 요청(머리·위 막대는 이것으로 그린다). */
  shownContext: RequestContext | null
  selected: string | null
  /** 마지막 분석 요청의 오류(결과 상태는 이것과 초안 비교로만 정한다). */
  error: ApiError | null
  /** 샘플 목록 조회 오류(분석 결과와 무관). 상태 조회가 실패하면 버전 표시만 빠진다. */
  listError: ApiError | null
  /** 이 작업 공간의 샘플 목록을 다 읽었는가(빈 목록과 읽는 중을 가른다). */
  listReady: boolean
  busy: boolean
  state: ResultState
  choose: (sample: Sample) => void
  /** 목록 기본 정렬의 첫 줄을 연다(처음 열 분석을 못 열었을 때). */
  openDefault: () => void
  edit: (text: string) => void
  runDraft: () => void
  setConfirmOn: (date: string | null) => void
  /** 1.23.0 설계 승인 상태·적용 시작일을 바꾸고 다시 분석한다(적용 시작일은 계산에 안 쓰지만 기록·표시에 남는다). */
  setDesignStatus: (status: DesignStatus) => void
  setEffectiveOn: (date: string | null) => void
  /** 1.28.0 변경 원인을 바꾸고 다시 분석한다(선주 요청만 계산이 바뀜 — 허용 지연, 그 밖에는 기록·리포트에만 남는다). */
  setCause: (cause: ChangeCause | null) => void
  /** 발주 보류를 넣거나(days) 빼고(null) 다시 분석한다(가정 계산). 표시 결과가 그 분석 ID이고 current일 때만 바꾼다. */
  changeHold: (analysisId: string, poId: string, days: number | null) => void
  /** 1.29.0 후행 설치를 켜거나 끄고 다시 분석한다(가정 계산, 바뀐 점을 보임). changeHold와 같은 조건. */
  changeOnboard: (analysisId: string, on: boolean) => void
  select: (id: string | null) => void
  /** 대안으로 분석 보기: 그 요청을 초안으로 쓰고 바로 분석한다(세대를 올린다). label을 주면 바뀐 점을 보인다. */
  open: (request: AnalysisRequest, label?: string) => void
  /** 가정 계산 바로 전 결과(그 계산이 끝나 지금 결과가 그 답일 때만). */
  comparison: Comparison | null
  /** 바뀐 점의 '되돌리기': 다시 계산하지 않고 바로 전 결과·요청으로 돌아간다. */
  restore: () => void
  /** 바뀐 점 닫기(결과는 그대로). */
  dismissComparison: () => void
  /** 비서가 분석한 요청·결과를 상세에 연다(초안 JSON도 그 요청으로). manual이면 사용자가 지난 분석을 직접 연 것(세대를 올린다). */
  adopt: (request: AnalysisRequest, result: AnalysisResult, manual: boolean) => void
  /** 비서가 변경 사유를 기록했을 때: 상세가 기록 전 그 요청(basis)이고 초안을 고치지 않았을 때만 사유를 반영한다. */
  refresh: (basis: AnalysisRequest, request: AnalysisRequest, result: AnalysisResult) => void
  /** 화면 세대: 비서가 보낼 때 잡아 두고 응답이 왔을 때 비교한다. */
  generation: ScreenGeneration
}

/**
 * openFirst: 목록이 오면 기본 정렬의 첫 줄을 연다. 결재함 '열기'처럼 처음부터 열 분석이 정해져 있으면 끈다
 * (첫 줄 분석이 그보다 늦게 끝나면 덮어써 다른 설계변경의 결재 띠가 보이므로). 화면이 처음 열릴 때만 읽는다.
 */
export function useAnalysisSession({ openFirst = true }: { openFirst?: boolean } = {}): AnalysisSession {
  const autoFirst = useRef(openFirst)
  const loaded = useRef<Sample[]>([])
  // 종료된 설계변경(결재 상태 목록): 처음 열 건에서 뺀다 — 목록 '전체' 칸과 같게
  const closed = useRef<ReadonlySet<string>>(new Set())
  const [health, setHealth] = useState<Health | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [chosen, setChosen] = useState<string | null>(null)
  const [draft, setDraftState] = useState('')
  const [shown, setShownState] = useState<{ result: AnalysisResult; body: unknown } | null>(null)
  // 비서가 사유를 기록했을 때(refresh) 지금 초안·결과와 비교하려고 마지막 값을 콜백에서도 읽는다
  const draftRef = useRef('')
  const shownRef = useRef<{ result: AnalysisResult; body: unknown } | null>(null)
  const setDraft = useCallback((text: string) => {
    draftRef.current = text
    setDraftState(text)
  }, [])
  const setShown = useCallback((value: { result: AnalysisResult; body: unknown } | null) => {
    shownRef.current = value
    setShownState(value)
  }, [])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [listError, setListError] = useState<ApiError | null>(null)
  const [listReady, setListReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const gate = useRef(new LatestGate())
  const [screen] = useState(() => new ScreenGeneration())

  // 최신 요청의 응답만 반영한다(먼저 보낸 요청이 늦게 와도 덮어쓰지 않게)
  // compare: 가정 계산이면 바로 전 결과(새 결과가 오면 바뀐 점으로 보임). 다른 계산이 시작되면 지운다
  const run = useCallback(async (body: unknown, compare: Comparison | null = null) => {
    const ticket = gate.current.begin()
    setBusy(true)
    setError(null)
    setComparison(null)
    try {
      const result = await api.analyses(body, ticket.signal)
      if (!gate.current.isLatest(ticket)) return
      setShown({ result, body })
      setComparison(compare && compare.before.request.change.ecn_id === result.request.change.ecn_id ? compare : null)
      setChosen(contextOf(body).ecnId)
      setSelected(null)
    } catch (caught) {
      if (!gate.current.isLatest(ticket)) return
      setError(caught instanceof ApiError ? caught : new ApiError(String(caught), 0))
    } finally {
      if (gate.current.isLatest(ticket)) setBusy(false)
    }
  }, [setShown])

  const choose = useCallback(
    (sample: Sample) => {
      screen.bump()
      setChosen(sample.ecn_id)
      setDraft(JSON.stringify(sample.request, null, 2))
      void run(sample.request)
    },
    [run, screen, setDraft],
  )

  useEffect(() => {
    let live = true
    const requests = gate.current
    api.health().then(
      (value) => live && setHealth(value),
      () => live && setHealth(null),
    )
    // 상태 목록이 실패해도 샘플은 연다(종료 건을 못 거를 뿐)
    const states = api.ecns().then(
      (list) => new Set(list.ecns.filter((item) => isClosed(item.status.state)).map((item) => item.status.ecn_id)),
      () => new Set<string>(),
    )
    Promise.all([api.samples(), states]).then(
      ([list, closedIds]) => {
        if (!live) return
        closed.current = closedIds
        loaded.current = list
        setSamples(list)
        setListReady(true)
        // 상태 확인으로 지도가 바뀌어 새로 열렸으면 확인 전 요청을 다시 분석, 아니면 목록 기본 정렬(마감일 임박 → 판정)의 첫 줄
        const pending = takeRerun(expectedWorkspace())
        if (pending) {
          screen.bump()
          setDraft(JSON.stringify(pending, null, 2))
          void run(pending)
          return
        }
        const first = autoFirst.current ? firstToOpen(list, closedIds) : undefined
        if (first) choose(first)
      },
      (caught: unknown) => {
        if (!live) return
        const failure = caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
        if (failure.code !== WORKSPACE_CHANGED) setListError(failure) // 바뀜이면 목록을 다시 읽어 새로 연다
      },
    )
    return () => {
      live = false
      requests.begin() // 작업 공간이 바뀌어 이 화면이 사라지면 진행 중 분석을 멈춘다
    }
  }, [choose, run, screen, setDraft])

  // 처음 열 분석(결재함 링크)을 못 열었을 때: 목록 첫 줄을 연다(목록이 아직 안 왔으면 오면 연다).
  // 언제 불려도 받은 목록을 보도록 상태가 아니라 ref(목록을 받을 때 채움)를 읽는다
  const openDefault = useCallback(() => {
    autoFirst.current = true
    const first = firstToOpen(loaded.current, closed.current)
    if (first) choose(first)
  }, [choose])

  const parsed = useMemo(() => parseRequest(draft), [draft])

  const runDraft = useCallback(() => {
    screen.bump()
    if (parsed.ok) void run(parsed.value)
  }, [parsed, run, screen])

  const edit = useCallback((text: string) => {
    screen.bump()
    setDraft(text)
  }, [screen, setDraft])

  /** 초안 글을 바꾸고 바로 다시 분석한다. compare를 주면 가정 계산(바뀐 점을 보임). */
  const rewrite = useCallback(
    (next: string, compare: Comparison | null = null) => {
      screen.bump()
      setDraft(next)
      const body = parseRequest(next)
      if (body.ok) void run(body.value, compare)
    },
    [run, screen, setDraft],
  )

  // 다른 설계변경을 열면 고른 ECN을 바로 바꾼다: 응답을 기다리는 동안 이전 ECN의 결재 띠·단추가 남아
  // 엉뚱한 ECN에 실행·종료·검토 취소를 누를 수 없게(목록의 choose와 같은 순서, DESIGN 13절)
  const open = useCallback(
    (request: AnalysisRequest, label?: string) => {
      const before = shownRef.current?.result
      setChosen(request.change.ecn_id ?? null)
      rewrite(JSON.stringify(request, null, 2), label && before ? { label, before } : null)
    },
    [rewrite],
  )

  const state = resultState(shown, busy, error !== null, parsed)
  const edits = useDraftEdits({ draft, shown, state, rewrite })

  const adopt = useCallback((request: AnalysisRequest, result: AnalysisResult, manual: boolean) => {
    if (manual) screen.bump()
    gate.current.begin() // 진행 중인 목록·확정일 분석의 늦은 응답은 버린다
    setBusy(false)
    setError(null)
    setComparison(null)
    setDraft(JSON.stringify(request, null, 2))
    setShown({ result, body: request })
    setChosen(request.change.ecn_id)
    setSelected(null)
  }, [screen, setDraft, setShown])

  const refresh = useCallback(
    (basis: AnalysisRequest, request: AnalysisRequest, result: AnalysisResult) => {
      if (!reflectsRecord(shownRef.current, draftRef.current, basis, result.analysis_id)) return
      gate.current.begin() // 같은 요청을 다시 계산하던 늦은 응답이 기록한 사유를 지우지 않게 버린다
      setBusy(false)
      setError(null)
      setComparison(null)
      setDraft(JSON.stringify(request, null, 2))
      setShown({ result, body: request })
    },
    [setDraft, setShown],
  )

  const restore = useCallback(() => {
    if (!comparison) return
    adopt(comparison.before.request, comparison.before, true)
  }, [comparison, adopt])

  const dismissComparison = useCallback(() => setComparison(null), [])

  return {
    health,
    samples,
    chosen,
    draft,
    draftValid: parsed.ok,
    draftContext: contextOf(parsed.ok ? parsed.value : null),
    result: shown?.result ?? null,
    shownContext: shown ? contextOf(shown.result.request) : null,
    selected,
    error,
    listError,
    listReady,
    busy,
    state,
    choose,
    openDefault,
    edit,
    runDraft,
    ...edits,
    open,
    comparison: state === 'current' ? comparison : null,
    restore,
    dismissComparison,
    select: setSelected,
    adopt,
    refresh,
    generation: screen,
  }
}
