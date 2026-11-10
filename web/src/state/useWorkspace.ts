// 작업 공간(지금 분석에 쓰는 지도): 지도 목록 · 활성 지도 · 전환 · 엑셀 가져오기(docs/operations.md(서비스) 6절).
// - 기대 토큰은 목록 응답과 전환 응답만 바꾼다. 적용 순서는 lib/workspace의 applyList(늦게 온 목록은 버림), 목록 읽기는
//   최신 요청만, 전환을 시작하면 기다리던 목록 읽기를 버린다.
// - '작업 공간이 바뀜'(409 workspace_changed) 알림을 받으면 목록을 다시 읽는다. 전환 요청이 연결 실패로 끝나 결과를
//   모르면 같은 전환을 한 번 더 보내 결과를 정한다(서버가 토큰을 먼저 대조하므로 두 번 바뀌지 않는다).
// - key(= 토큰)가 바뀌면 화면이 새 작업 공간으로 다시 연다(세션·비서가 key를 보고 비움).
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  WORKSPACE_CHANGED,
  api,
  onWorkspaceChanged,
  setExpectedWorkspace,
  type ConfirmedMapping,
  type ImportPreview,
  type MappingOverrides,
  type MappingProposal,
  type SnapshotInfo,
  type SnapshotList,
  type StatusUpdate,
  type UpdateEvent,
} from '@/api/client'
import { LatestGate } from '@/lib/latest'
import { NOTHING_APPLIED, activeInfo, applyList, changeNotice, type Applied, type Notice } from '@/lib/workspace'

/** 상태 갱신 결과: 남긴 기록(실패면 null)과 실패(바뀜 알림이면 null — 목록을 다시 읽음). */
export interface UpdateOutcome {
  event: UpdateEvent | null
  failure: ApiError | null
}

export interface WorkspaceState {
  list: SnapshotList | null
  active: SnapshotInfo | null
  /** 작업 공간 토큰. 바뀌면 상세·비서를 새로 연다. */
  key: string | null
  notice: Notice | null
  /** 전환(활성화·확정) 중. */
  switching: boolean
  reload: () => void
  /** 지도를 바꾼다. 실패하면 그 오류(바뀜 알림이면 목록을 다시 읽으므로 null). */
  activate: (snapshotId: string) => Promise<ApiError | null>
  /** 엑셀을 올려 매핑 제안(열 확인)을 받는다(아직 지도를 만들지 않음). */
  stage: (file: File, signal?: AbortSignal) => Promise<MappingProposal>
  /** 시트 상태·머리글 행을 정해 다시 제안받는다. */
  propose: (importId: string, overrides: MappingOverrides, signal?: AbortSignal) => Promise<MappingProposal>
  /** 확정 매핑으로 읽어 품질 리포트를 받는다. */
  submit: (importId: string, version: number, mapping: ConfirmedMapping, signal?: AbortSignal) => Promise<ImportPreview>
  /** 그 버전의 읽기 결과로 만든 지도로 전환한다. */
  confirm: (importId: string, version: number) => Promise<ApiError | null>
  /** 상태 확인·수정을 지금 지도에 덮어써 새 작업 공간으로 바꾼다(거부·충돌이면 바꾸지 않음). */
  applyUpdate: (body: StatusUpdate) => Promise<UpdateOutcome>
  /** 상태 올리기 확정: 그 버전의 읽기 결과를 지금 지도에 덮어쓴다(지도가 그사이 바뀌었으면 event·failure 둘 다 null). */
  confirmStatus: (importId: string, version: number) => Promise<UpdateOutcome>
  dismissNotice: () => void
}

export function useWorkspace(): WorkspaceState {
  const [applied, setApplied] = useState<Applied>(NOTHING_APPLIED)
  const appliedRef = useRef<Applied>(NOTHING_APPLIED)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [switching, setSwitching] = useState(false)
  const gate = useRef(new LatestGate())

  const apply = useCallback((next: SnapshotList, reason: 'switch' | 'sync') => {
    const state = applyList(appliedRef.current, next)
    if (!state) return
    const before = appliedRef.current.list
    appliedRef.current = state
    setExpectedWorkspace(next.workspace) // 다음 묶인 요청부터 새 토큰(다시 그리기 전에)
    setApplied(state)
    const text = changeNotice(before, next, reason)
    if (text) setNotice(text)
  }, [])

  const load = useCallback(
    (reason: 'switch' | 'sync') => {
      const ticket = gate.current.begin()
      api.snapshots(ticket.signal).then(
        (list) => {
          if (gate.current.isLatest(ticket)) apply(list, reason)
        },
        (caught: unknown) => {
          if (!gate.current.isLatest(ticket)) return
          if (caught instanceof DOMException && caught.name === 'AbortError') return
          const message = caught instanceof ApiError ? caught.message : String(caught)
          setNotice({ tone: 'danger', text: `지도 목록 불러오기 실패 · ${message}` })
        },
      )
    },
    [apply],
  )
  const reload = useCallback(() => load('sync'), [load])

  useEffect(() => {
    reload()
    return onWorkspaceChanged(reload)
  }, [reload])

  const switchWith = useCallback(
    async (send: () => Promise<SnapshotList>): Promise<ApiError | null> => {
      gate.current.begin() // 기다리던 목록 읽기는 버린다(전환 결과가 새 기준)
      setSwitching(true)
      const attempt = async (): Promise<SnapshotList | ApiError> => {
        try {
          return await send()
        } catch (caught) {
          return caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
        }
      }
      try {
        let outcome = await attempt()
        // 연결이 끊겨 결과를 모르면 같은 전환을 한 번 더 보낸다. 서버는 기대 토큰을 먼저 대조하므로 첫 요청이 이미
        // 바꿨거나 처리 중이면(전환 잠금을 기다린 뒤) 409로 거절되고, 닿지 않았으면 이번에 바꾼다 — 어느 쪽이든 결과가 정해진다
        const retried = outcome instanceof ApiError && outcome.status === 0
        if (retried) outcome = await attempt()
        if (!(outcome instanceof ApiError)) {
          apply(outcome, 'switch')
          return null
        }
        if (outcome.code === WORKSPACE_CHANGED) {
          // 바뀜 알림이 목록을 다시 읽는다. 다시 보낸 끝의 409면 내 첫 요청이 바꾼 것이라 '바꿨어요'로 읽는다
          if (retried) load('switch')
          return null
        }
        if (outcome.status === 0) load('switch') // 두 번 다 닿지 않음: 목록이라도 다시 읽어 실제 상태에 맞춘다
        return outcome
      } finally {
        setSwitching(false)
      }
    },
    [apply, load],
  )

  const activate = useCallback(
    async (snapshotId: string) => {
      const failure = await switchWith(() => api.activate(snapshotId))
      if (failure) setNotice({ tone: 'danger', text: `지도 전환 실패 · ${failure.message}` })
      return failure
    },
    [switchWith],
  )
  const confirm = useCallback(
    (importId: string, version: number) => switchWith(() => api.confirmImport(importId, version)),
    [switchWith],
  )
  const applyUpdate = useCallback(
    async (body: StatusUpdate): Promise<UpdateOutcome> => {
      let event: UpdateEvent | null = null
      const failure = await switchWith(async () => {
        const applied = await api.applyUpdate(body)
        event = applied.event
        return applied.snapshots
      })
      return { event, failure }
    },
    [switchWith],
  )
  const confirmStatus = useCallback(
    async (importId: string, version: number): Promise<UpdateOutcome> => {
      let event: UpdateEvent | null = null
      const failure = await switchWith(async () => {
        const applied = await api.confirmStatusImport(importId, version)
        event = applied.event
        return applied.snapshots
      })
      return { event, failure }
    },
    [switchWith],
  )
  const stage = useCallback((file: File, signal?: AbortSignal) => api.stageImport(file, file.name, signal), [])
  const propose = useCallback(
    (importId: string, overrides: MappingOverrides, signal?: AbortSignal) =>
      api.proposeImport(importId, overrides, signal),
    [],
  )
  const submit = useCallback(
    (importId: string, version: number, mapping: ConfirmedMapping, signal?: AbortSignal) =>
      api.submitMapping(importId, version, mapping, signal),
    [],
  )
  const dismissNotice = useCallback(() => setNotice(null), [])

  const list = applied.list
  return {
    list,
    active: activeInfo(list),
    key: list?.workspace ?? null,
    notice,
    switching,
    reload,
    activate,
    stage,
    propose,
    submit,
    confirm,
    applyUpdate,
    confirmStatus,
    dismissNotice,
  }
}
