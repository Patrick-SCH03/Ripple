// 사전 점검(계약 1.32.0, docs/engine.md(사전 점검)): 판정과 분리된 확인 항목을 상세에 보이는 순서·이름으로 고른다.
// 연결 지도에 거는 규칙 검사(3D 형상 검사가 아님)이고 판정·금액에 넣지 않는다. 항목·건수는 결과의 prechecks 그대로이고
// (비면 응답에서 빠져 ?? []), 여기서는 수준 순 정렬 · P-06(현장 공유) 묶기 · 이름 고르기만 한다.
// P-06은 착수한 블록이면 거의 늘 걸려(시연 지도 300건 중 197건) 다른 확인 항목을 묻지 않게 '현장 통보' 한 묶음으로 맨 아래에 둔다.
import type { AnalysisResult, GraphNode, PrecheckItem, PrecheckLevel, PrecheckLink } from '@/api/client'
import { nodeFor } from './assistant'
import { versionAtLeast } from './delayRipple'
import { ACTIVITY_NAMES, RELATION_NAMES, activityName, codeOf } from './labels'

export const PRECHECK_LEVEL_NAMES: Record<PrecheckLevel, string> = {
  check: '확인 필요',
  caution: '주의',
  unchecked: '점검 불가',
}

const LEVEL_ORDER: Record<PrecheckLevel, number> = { check: 0, caution: 1, unchecked: 2 }

/** 이 규칙을 계산하는 계약 판(1.32.0 안에서 추가) — 앞 판의 기록에는 사전 점검 묶음을 그리지 않는다. */
const PRECHECK_CONTRACT = '1.32.0'

const NOTIFY_RULE = 'P-06'

const EVIDENCE_NAMES: Record<string, string> = {
  ...RELATION_NAMES,
  secondary_drawing: '다른 분야 도면',
  performed_by: '수행',
}

export interface NotifyGroup {
  /** 블록마다 한 항목(서버 키 순). */
  items: PrecheckItem[]
  /** 위험 이유 한 줄(규칙마다 같은 글). */
  reason: string
  /** 같은 유형 합성 NCR 건수(실데이터 모드는 null). */
  ncr: number | null
}

export interface PrecheckView {
  /** P-06 밖 항목: 확인 필요 → 주의 → 점검 불가, 같은 수준이면 규칙 → 키 순. */
  items: PrecheckItem[]
  /** P-06 현장 공유 묶음(없으면 null). */
  notify: NotifyGroup | null
  /** 머리 요약 '확인 필요 2 · 주의 1 · 현장 통보 2곳'(0은 뺀다). 걸린 것이 없으면 ''. */
  summary: string
}

/** 결과 → 사전 점검 묶음. 이 판을 계산하지 않은 옛 기록이면 null(묶음을 그리지 않음). */
export function precheckView(result: Pick<AnalysisResult, 'prechecks' | 'versions'>): PrecheckView | null {
  if (!versionAtLeast(result.versions?.contract ?? '', PRECHECK_CONTRACT)) return null
  const all = result.prechecks ?? []
  const items = all
    .filter((item) => item.rule_id !== NOTIFY_RULE)
    .sort(
      (a, b) =>
        LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] || a.rule_id.localeCompare(b.rule_id) || a.key.localeCompare(b.key),
    )
  const notifyItems = all.filter((item) => item.rule_id === NOTIFY_RULE).sort((a, b) => a.key.localeCompare(b.key))
  const notify = notifyItems.length
    ? { items: notifyItems, reason: notifyItems[0].reason, ncr: notifyItems[0].ncr_count ?? null }
    : null
  const count = (level: PrecheckLevel) => items.filter((item) => item.level === level).length
  const summary = [
    ...(['check', 'caution', 'unchecked'] as const).map((level) =>
      count(level) > 0 ? `${PRECHECK_LEVEL_NAMES[level]} ${count(level)}` : '',
    ),
    notify ? `현장 통보 ${notify.items.length}곳` : '',
  ]
    .filter(Boolean)
    .join(' · ')
  return { items, notify, summary }
}

/** 엔터티 이름: 영향 지도 카드 이름 → 직영 → 새 부재 → 공정이면 '블록 공정' → 코드. */
export function entityName(id: string, nodes: readonly Pick<GraphNode, 'id' | 'label'>[]): string {
  const node = nodes.find((n) => n.id === id)
  if (node) return node.label
  if (id === 'direct') return '직영'
  if (id.startsWith('NEW:')) return '새 부재'
  const kind = id.slice(id.lastIndexOf(':') + 1)
  if (ACTIVITY_NAMES[kind]) return activityName(id)
  return codeOf(id)
}

/** 근거 연결 한 줄: '새 배관 스풀 1 →(관통) A11C 판 1 · 변경으로 생김'. */
export function evidenceText(link: PrecheckLink, nodes: readonly Pick<GraphNode, 'id' | 'label'>[]): string {
  const relation = EVIDENCE_NAMES[link.relation] ?? link.relation
  const tail = link.virtual ? ' · 변경으로 생김' : ''
  return `${entityName(link.src, nodes)} →(${relation}) ${entityName(link.dst, nodes)}${tail}`
}

/** 대상 단추: 영향 지도에 있는 엔터티만 누를 수 있다(누르면 그 카드를 골라 근거를 연다). */
export function targetsOf(
  item: Pick<PrecheckItem, 'targets'>,
  nodes: readonly Pick<GraphNode, 'id' | 'label'>[],
  limit = 3,
): { id: string; name: string; node: string | null }[] {
  return item.targets.slice(0, limit).map((id) => ({ id, name: entityName(id, nodes), node: nodeFor(id, nodes) }))
}

/** '같은 유형 합성 NCR n건'(합성 묶음 — 실데이터 모드는 건수가 없어 칩도 없다). */
export function ncrText(count: number | null | undefined): string | null {
  return count == null ? null : `같은 유형 합성 NCR ${count}건`
}

/** 서버 P-06 문장('B31P 블록에서 이미 한 공정(…)을 맡은 직영·해송 작업반에 변경 내용 통보 필요')의 꼴. */
const NOTIFY_TEXT = /^(\S+) 블록에서 이미 한 공정\((.+)\)을 맡은 (.+)에 변경 내용 통보 필요$/

/**
 * 현장 통보 한 항목을 핵심 한 줄 + 보조 한 줄로: 'B31P · 직영·해송 작업반에 변경 통보 필요' / '이미 한 공정 · 소조립 완료, …'.
 * 서버 문장 꼴이 다르면(바뀐 판·실데이터) 원문 그대로 한 줄(보조 없음) — 글을 지어내지 않는다.
 */
export function notifyLine(text: string): { head: string; done: string | null } {
  const match = NOTIFY_TEXT.exec(text)
  if (!match) return { head: text, done: null }
  const [, block, done, who] = match
  return { head: `${block} · ${who}에 변경 통보 필요`, done: `이미 한 공정 · ${done}` }
}
