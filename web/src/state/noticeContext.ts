// 통보 기록 다리(계약 1.28.0): 업무 화면(Workbench)이 고른 설계변경의 기록 상태를 알림 초안 카드에 넘긴다.
// 카드는 지금 상세에 보이는 분석의 초안일 때만 이것을 쓴다(지난 분석의 초안에 통보를 잘못 붙이지 않게).
import { createContext } from 'react'
import type { NoticeLog } from '@/api/client'
import type { NoticeState } from '@/lib/notices'

export interface NoticeBridge {
  /**
   * 상세 결과가 계산을 마친 지금 결과이고 그 설계변경 = 따라가는 기록의 설계변경인가. 다른 설계변경을 고른 직후(새 분석
   * 전·실패)에는 앞 결과의 카드가 남아 있어, 그때 누르면 다른 설계변경의 감사 사슬에 붙으므로 막는다.
   */
  ready: boolean
  /** 고른 설계변경에 기록(개정)이 있는가 — 통보는 기록한 개정에 붙인다. */
  recorded: boolean
  /** 이 계정이 통보 기록을 남길 수 있는가(기록 권한). */
  canLog: boolean
  busy: boolean
  /** 받는 쪽 열쇠(noticeKey) → 단계별 마지막 날짜. */
  states: Map<string, NoticeState>
  /** 오늘(KST, YYYY-MM-DD) — 날짜 입력의 기본값·상한. */
  today: string
  log: (log: NoticeLog) => Promise<string | null>
}

export const NoticeContext = createContext<NoticeBridge | null>(null)
