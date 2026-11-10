// 분석 기준(설계변경 목록이 없는 지도 — 엑셀로 가져온 지도): AI 비서가 새 요청에 쓰는 호선·기준일의 단일 출처.
// 기본 지도는 고른 설계변경의 요청이 기준이라 쓰지 않는다(docs/operations.md(서비스) 6절).
// 기준일 기본값 = 자료 기준일(지도 안의 마지막 상태 날짜: 발주 관측·단계 진입일·공정 실적), 없으면 오늘(한국 시간).
// 상태 함수는 기준일 뒤에 적힌 기록을 쓰지 않고, 마지막 기록 뒤는 계획 간격으로 추정한다(docs/domain.md 3절).
import type { SnapshotInfo, TurnContext } from '@/api/client'
import { DEFAULT_HORIZON_DAYS } from './assistant'
import { formatDay } from './format'

export interface Basis {
  shipIds: string[]
  asOf: string
}

/** 오늘(한국 시간) yyyy-mm-dd. */
export function todayKst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}

export function defaultBasis(info: SnapshotInfo, today: string): Basis {
  return { shipIds: [...info.ship_ids], asOf: info.status_date ?? today }
}

/** 기준일과 자료 기준일이 다를 때 계산이 어떻게 달라지는지 한 줄(같으면 null). */
export function basisNote(basis: Basis, info: SnapshotInfo): string | null {
  const data = info.status_date
  if (!data) return '지도에 상태 기록(발주 관측·진입일·공정 실적) 없음 · 상태는 계획 일정으로 추정'
  if (basis.asOf > data) return `자료 기준일(${formatDay(data)}) 뒤 상태는 계획 간격으로 추정`
  if (basis.asOf < data) return `기준일 이후 상태 기록은 제외(자료 기준일 ${formatDay(data)})`
  return null
}

/** 비서 맥락. 호선을 하나도 고르지 않았거나 기준일이 비면 null(보내지 않음). */
export function basisContext(basis: Basis): TurnContext | null {
  if (basis.shipIds.length === 0 || !/^\d{4}-\d{2}-\d{2}$/.test(basis.asOf)) return null
  return { ship_ids: basis.shipIds, as_of: basis.asOf, confirm_on: null, horizon_days: DEFAULT_HORIZON_DAYS }
}
