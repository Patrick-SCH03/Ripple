// 설계변경을 연 차례(업무 화면): 목록에서 고르기·비서·문서 접수·기록 열기가 상세를 열 때마다 1씩 센다. 기록 열기
// (useRecordLinks)는 기록을 읽은 뒤에 열므로, 그사이 다른 설계변경을 열었으면 늦게 온 기록이 그 화면을 덮지 않게
// 이 차례로 가린다.
import { useCallback, useRef } from 'react'
import type { AnalysisRequest, AnalysisResult, Sample } from '@/api/client'
import type { AnalysisSession } from './useAnalysisSession'

export interface OpenOrder {
  /** 분석을 상세에 연다(비서·문서 접수·지난 차례). session.adopt와 같고 차례만 센다. */
  adopt: AnalysisSession['adopt']
  /** 목록에서 고른다. 좁은 화면에서는 고른 뒤 상세 탭으로 넘어간다. */
  choose: (sample: Sample) => void
  /** 기록 열기처럼 나중에 여는 일의 차례를 잡는다. */
  begin: () => number
  /** 잡은 차례 뒤로 다른 설계변경을 열지 않았나. */
  isLatest: (pick: number) => boolean
}

export function useOpenOrder(
  session: AnalysisSession,
  compact: boolean,
  showTab: (tab: 'detail') => void,
): OpenOrder {
  const picks = useRef(0)
  const { adopt: adoptResult, choose: chooseSample } = session
  const adopt = useCallback(
    (request: AnalysisRequest, result: AnalysisResult, manual: boolean) => {
      picks.current += 1
      adoptResult(request, result, manual)
    },
    [adoptResult],
  )
  const choose = useCallback(
    (sample: Sample) => {
      picks.current += 1
      chooseSample(sample)
      if (compact) showTab('detail')
    },
    [chooseSample, compact, showTab],
  )
  const begin = useCallback(() => (picks.current += 1), [])
  const isLatest = useCallback((pick: number) => pick === picks.current, [])
  return { adopt, choose, begin, isLatest }
}
