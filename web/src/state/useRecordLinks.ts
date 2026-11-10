// 기록 열기(docs/records.md(기록·결재)): 목록의 기록된 설계변경과 결재·현황 결재함의 '열기'(/app?record=R-…).
// 기록을 읽은 뒤 그 요청을 지금 지도에서 다시 분석한다(숫자는 지금 지도 기준, 기록 당시 숫자는 이력 탭). 읽는 사이
// 다른 설계변경을 열었으면(useOpenOrder의 차례) 늦게 온 기록은 버린다.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, type EcnListItem } from '@/api/client'
import { APP_PATH } from '@/lib/route'
import type { Notice } from '@/lib/workspace'
import type { AnalysisSession } from './useAnalysisSession'
import type { OpenOrder } from './useOpenOrder'
import { navigate } from './useRoute'

interface Options {
  session: AnalysisSession
  /** 설계변경을 연 차례. */
  order: Pick<OpenOrder, 'begin' | 'isLatest'>
  /** 결재 상태 목록을 다시 읽는다(useRecords.reload). */
  reloadRecords: () => void
  /** 화면을 처음 열 때 주소에서 읽은 결재함의 기록 ID(없으면 null). */
  linkedRecord: string | null
  compact: boolean
  showTab: (tab: 'detail') => void
}

export interface RecordLinks {
  /** 기록을 열지 못했을 때의 알림(결재함 링크·목록의 기록된 설계변경 공통). */
  notice: Notice | null
  dismissNotice: () => void
  openRecordId: (recordId: string) => void
  openRecord: (item: EcnListItem) => void
}

export function useRecordLinks({ session, order, reloadRecords, linkedRecord, compact, showTab }: Options): RecordLinks {
  const { open: openRequest, openDefault } = session
  const [notice, setNotice] = useState<Notice | null>(null)
  /**
   * 기록을 읽어 그 요청을 지금 지도에서 다시 분석한다. 읽는 사이 다른 설계변경을 열었으면 늦게 온 기록은 버린다.
   * 못 읽으면 onFail(이유, 그사이 다른 것을 열지 않았는가)을 부른다(목록 다시 읽기는 부르는 쪽이 정한다).
   */
  const { begin, isLatest } = order
  const openRecorded = useCallback(
    (recordId: string, onFail: (reason: string, latest: boolean) => void) => {
      const pick = begin()
      api.record(recordId).then(
        (found) => {
          if (!isLatest(pick)) return
          openRequest(found.body.result.request)
          if (compact) showTab('detail')
        },
        (caught: unknown) => onFail(caught instanceof ApiError ? caught.message : '연결 끊김', isLatest(pick)),
      )
    },
    [openRequest, compact, showTab, begin, isLatest],
  )
  // 샘플에 없는 기록된 설계변경: 마지막 기록의 요청으로 지금 지도에서 다시 분석한다. 기록을 못 읽으면 알리고 목록을
  // 다시 읽는다(눌러도 반응이 없어 보이지 않게). 그사이 다른 설계변경을 열었으면 늦은 실패는 조용히 버린다
  const openRecordId = useCallback(
    (recordId: string) => {
      setNotice(null)
      openRecorded(recordId, (reason, latest) => {
        if (!latest) return
        setNotice({ tone: 'danger', text: `기록 열기 실패(${reason}) · 목록 다시 불러옴 — 다시 선택` })
        reloadRecords()
      })
    },
    [openRecorded, reloadRecords],
  )
  const openRecord = useCallback((item: EcnListItem) => openRecordId(item.status.record_id), [openRecordId])
  // 결재함에서 연 기록: 그 개정의 기록된 분석을 한 번 열고 주소에서는 지운다(새로 고침·뒤로 가기로 다시 열리지 않게).
  // 못 열면 알리고 목록 첫 줄을 연다(빈 화면으로 두지 않게)
  const linked = useRef(false)
  useEffect(() => {
    if (linked.current || !linkedRecord) return
    linked.current = true
    navigate(APP_PATH, { replace: true })
    openRecorded(linkedRecord, (reason, latest) => {
      setNotice({ tone: 'danger', text: `결재함에서 고른 기록 열기 실패(${reason}) — 목록에서 다시 선택` })
      reloadRecords()
      if (latest) openDefault()
    })
  }, [linkedRecord, openRecorded, openDefault, reloadRecords])

  return { notice, dismissNotice: () => setNotice(null), openRecordId, openRecord }
}
