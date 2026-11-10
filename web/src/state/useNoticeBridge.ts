// 통보 기록 다리 만들기(계약 1.28.0): 분석 세션(지금 보이는 결과)과 고른 설계변경의 기록 상태를 묶어 알림 카드에 넘긴다.
import { useMemo } from 'react'
import { todayKst } from '@/lib/basis'
import { noticeStates } from '@/lib/notices'
import type { NoticeBridge } from './noticeContext'
import type { AnalysisSession } from './useAnalysisSession'
import type { RecordsState } from './useRecords'

export function useNoticeBridge(session: AnalysisSession, records: RecordsState, canLog: boolean): NoticeBridge {
  const { ecnId, detail, detailReady, busy, notice } = records
  // 계산을 마친 지금 결과의 설계변경(다시 계산 중·거절·초안 수정 뒤면 없음)
  const shownEcn = session.state === 'current' ? (session.result?.request.change.ecn_id ?? null) : null
  // 통보는 실제로 한 일이라 지도 기준일이 아니라 오늘(KST)이 기본·상한이다(서버도 KST 오늘로 대조)
  const today = todayKst()
  return useMemo<NoticeBridge>(
    () => ({
      ready: detailReady && shownEcn !== null && shownEcn === ecnId,
      recorded: detailReady && detail !== null && detail.status.ecn_id === shownEcn,
      canLog,
      busy: busy !== null,
      states: noticeStates(detail?.audit ?? []),
      today,
      log: notice,
    }),
    [detailReady, shownEcn, ecnId, detail, canLog, busy, today, notice],
  )
}
