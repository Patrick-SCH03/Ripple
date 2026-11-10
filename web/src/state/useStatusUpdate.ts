// 현장 상태 확인(상세의 상태 확인·수정): 지도가 바뀌면 업무 화면이 새로 열리므로 지금 요청을 맡겨 두고 새 화면이
// 한 번 다시 분석한다(lib/rerun). 실패하거나 지도가 그대로면(재확인) 맡긴 것을 지운다.
import { useCallback } from 'react'
import type { StatusUpdate } from '@/api/client'
import { clearRerun, stashRerun } from '@/lib/rerun'
import type { AnalysisSession } from './useAnalysisSession'
import type { WorkspaceState } from './useWorkspace'

/** 상태 갱신을 보낸다: 성공이면 null, 아니면 이유 문장. */
export function useStatusUpdate(
  workspace: WorkspaceState,
  session: AnalysisSession,
): (update: StatusUpdate) => Promise<string | null> {
  const shownRequest = session.result?.request ?? null
  const shownMap = session.result?.versions.snapshot_id ?? null
  const { applyUpdate, key: workspaceKey } = workspace
  return useCallback(
    async (update: StatusUpdate): Promise<string | null> => {
      if (shownRequest && workspaceKey) stashRerun(workspaceKey, shownRequest)
      // 이 화면이 본 지도에만 적용(그사이 다른 사람이 바꿨으면 409 — 모르는 변경을 덮어쓰지 않게)
      const { event, failure } = await applyUpdate({ ...update, base_snapshot_id: shownMap })
      if (failure || !event || event.snapshot_id === event.base_snapshot_id) clearRerun()
      if (!failure) return event ? null : '다른 곳에서 지도 바뀜 · 지금 지도로 다시 불러옴 — 다시 확인 필요'
      return failure.problems.length > 0 ? `${failure.message}: ${failure.problems.join(' / ')}` : failure.message
    },
    [applyUpdate, shownRequest, shownMap, workspaceKey],
  )
}
