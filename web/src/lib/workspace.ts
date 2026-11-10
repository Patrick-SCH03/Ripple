// 작업 공간 목록을 적용하는 순서(docs/operations.md(서비스) 6절). 늦게 도착한 목록 응답이 방금 바꾼 작업 공간을 되돌리지 않게:
// 같은 서버 인스턴스 안에서는 세대가 낮은 목록을 버리고, 서버가 다시 켜져 새 인스턴스의 목록을 적용했으면 그 전
// 인스턴스의 목록은 다시 받지 않는다.
import type { Freshness, SnapshotInfo, SnapshotList } from '@/api/client'
import { formatDay } from './format'

export interface Applied {
  list: SnapshotList | null
  /** 새 인스턴스로 넘어가며 지난 서버 인스턴스. */
  retired: ReadonlySet<string>
}

export const NOTHING_APPLIED: Applied = { list: null, retired: new Set() }

/** next를 적용한 상태. 적용하지 않으면(늦은 응답) null. 같은 목록이면 그대로 돌려준다(키가 그대로라 화면을 다시 열지 않음). */
export function applyList(state: Applied, next: SnapshotList): Applied | null {
  const current = state.list
  if (state.retired.has(next.instance)) return null
  if (current && current.instance === next.instance && next.generation < current.generation) return null
  const retired =
    current && current.instance !== next.instance ? new Set([...state.retired, current.instance]) : state.retired
  return { list: next, retired }
}

export function activeInfo(list: SnapshotList | null): SnapshotInfo | null {
  return list?.items.find((item) => item.snapshot_id === list.active_snapshot_id) ?? null
}

/** 기본 합성 지도이거나 그 지도에서 상태만 갱신한 지도인가(설계변경 샘플 목록이 있는 지도). */
export function samplesMap(list: SnapshotList | null, info: SnapshotInfo | null): boolean {
  if (!info) return false
  if (info.default) return true
  const root = info.update?.lineage_root
  return !!root && !!list?.items.some((item) => item.default && item.snapshot_id === root)
}

/** 자료 날짜 줄(지도 메뉴, docs/domain.md 12절): 최신 날짜와 7일 이상 미확인 발주 수. stale = 확인할 게 있음. */
export function freshnessLines(freshness: Freshness): { lines: string[]; stale: boolean } {
  const day = (value: string | null | undefined) => (value ? formatDay(value) : '기록 없음')
  const orders =
    freshness.open_orders > 0
      ? ` · 입고 전 ${freshness.open_orders}건 중 7일 이상 미확인 발주 ${freshness.stale_orders}건`
      : ''
  return {
    lines: [`발주 상태 최신 ${day(freshness.po_latest)}${orders}`, `공정 실적 최신 ${day(freshness.activity_latest)}`],
    stale: freshness.stale_orders > 0,
  }
}

/** 화면 위 알림 한 줄. info = 내가 한 일의 결과, warning = 모르는 사이 바뀐 것, danger = 실패. */
export interface Notice {
  tone: 'info' | 'warning' | 'danger'
  text: string
}

/** 작업 공간이 바뀌었을 때 알림. 처음 연 것이면 복구 실패만 알림(없으면 null). */
export function changeNotice(before: SnapshotList | null, after: SnapshotList, reason: 'switch' | 'sync'): Notice | null {
  if (!before) return after.restore_problem ? { tone: 'warning', text: after.restore_problem } : null
  if (before.workspace === after.workspace) return null
  const info = activeInfo(after)
  const name = info?.name ?? after.active_snapshot_id
  const stamp = info?.update
  if (reason === 'switch' && stamp && stamp.base_snapshot_id === before.active_snapshot_id) {
    // 상태 갱신(확인·올리기)으로 지금 지도에서 이어진 지도: 바꾼 게 아니라 반영한 것
    const changed = stamp.status_changed + stamp.plan_changed + stamp.activities
    const what = changed > 0 ? `바뀐 것 ${changed}건` : `확인 ${stamp.confirmed_only}건`
    const after = stamp.origin === 'confirm' ? '같은 조건으로 다시 계산' : '목록·분석을 새 상태로 다시 계산'
    return { tone: 'info', text: `상태 반영(${what}) · ${after}` }
  }
  if (reason === 'switch') return { tone: 'info', text: `지도 전환: ${name}` }
  return {
    tone: 'warning',
    text: `지도 변경 또는 서버 재시작 · 지금 지도(${name})로 다시 불러옴 — 진행 중이던 분석·대화는 새로 시작`,
  }
}

/** 지도 한 줄 설명: 데이터 종류 · 가져온 때(가져온 지도) · 규모. */
export function mapDetail(info: SnapshotInfo, now: Date = new Date()): string {
  const kind = info.data_mode === 'real' ? '실제 데이터' : '합성 데이터'
  const counts = `블록 ${info.counts.blocks} · 부재 ${info.counts.parts.toLocaleString('ko-KR')} · 발주 ${info.counts.purchase_orders}`
  if (info.default) return `${kind} · 기본 · ${counts}`
  if (info.update) {
    const by = `${importedWhen(info.update.at, now)} ${info.update.by} ${info.update.origin === 'excel' ? '상태 올리기' : '상태 확인'}`
    return [kind, by, counts].join(' · ')
  }
  const when = info.imported_at ? importedWhen(info.imported_at, now) : null
  return [kind, when ? `${when} 가져옴` : null, counts].filter(Boolean).join(' · ')
}

/** 가져온 때: 오늘이면 '오늘 15:30', 아니면 '10월 8일 15:30'(보는 사람의 시간대 — 한국이면 KST). */
export function importedWhen(iso: string, now: Date = new Date()): string {
  const at = new Date(iso)
  const day = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
  const time = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  return day(at) === day(now) ? `오늘 ${time}` : `${at.getMonth() + 1}월 ${at.getDate()}일 ${time}`
}
