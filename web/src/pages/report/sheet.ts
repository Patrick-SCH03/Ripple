// 설계변경 검토서(A4 세로 출력, DESIGN.md 14절)의 문서 전용 표기: 문서 머리 · 변경 내용·사유 · 핵심 수치 표 · 영향 범위 요약 ·
// 결재란 · 꼬리(출처·쪽 머리). 숫자는 모두 그 기록 본문의 분석 결과와 감사 줄 그대로이고(새 계산 없음), 화면 상세와 같은
// 함수(keyNumbers·orderedCard)를 쓴다. 실제 야드 양식을 본 적이 없어 '통보서 호환'이 아닌 일반 사내 검토서 구성이다.
import type { AnalysisResult, AuditEntry, Impact } from '@/api/client'
import { causeName } from '@/lib/request'
import { formatDay } from '@/lib/format'
import { IMPACT_NAMES, OP_NAMES, SEVERITY_RANK } from '@/lib/labels'
import { costHead } from '@/lib/costSplit'
import { orderedCard } from '@/lib/ordered'
import { keyNumbers } from '@/lib/summary'
import { blockLabel } from '@/lib/weightChange'

type ChangeOp = AnalysisResult['request']['change']['ops'][number]

export const SHEET_TITLE = '설계변경 검토서'
const SOURCE_NOTE = 'Ripple 분석 결과'

const KST = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** 시각(ISO) → '2026-10-20 14:05 KST'(문서 표기, DESIGN.md 8절 — 표는 2026-10-30). 없거나 틀리면 '—'. */
export function kstStamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const p = Object.fromEntries(KST.formatToParts(date).map((part) => [part.type, part.value]))
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute} KST`
}

/** 시각(ISO) → KST 날짜 '2026-10-20'(결재란 칸). */
export function kstDay(iso: string | null | undefined): string {
  const stamp = kstStamp(iso)
  return stamp === '—' ? '' : stamp.slice(0, 10)
}

// ---------- 변경 내용 ----------

/** 그래프 노드 이름(대상 부재는 분석 그래프에 있다), 없으면 ID 그대로. */
function namer(result: Pick<AnalysisResult, 'graph'>): (id: string) => string {
  const labels = new Map(result.graph.nodes.map((node) => [node.id, node.label]))
  return (id) => labels.get(id) ?? id
}

const DIMENSION_NAMES: Record<string, string> = {
  length_mm: '길이',
  width_mm: '폭',
  height_mm: '높이',
  diameter_mm: '지름',
}

/** 대상 부재 목록: 3개까지 이름, 넘으면 '외 n'. */
function partsOf(ids: readonly string[], name: (id: string) => string): string {
  const shown = ids.slice(0, 3).map(name).join(', ')
  return ids.length > 3 ? `${shown} 외 ${ids.length - 3}` : shown
}

/** 연산 한 줄(현장 말): '두께 변경 · 판 3장(…) · 17mm → 20mm'. */
export function opLine(op: ChangeOp, name: (id: string) => string): string {
  const head = OP_NAMES[op.op] ?? op.op
  switch (op.op) {
    case 'thickness':
      return `${head} · ${op.part_ids.length}개(${partsOf(op.part_ids, name)}) · ${op.from_mm}mm → ${op.to_mm}mm`
    case 'grade':
      return `${head} · ${op.part_ids.length}개(${partsOf(op.part_ids, name)}) · ${op.from_grade} → ${op.to_grade}`
    case 'dimension':
      return `${head} · ${op.part_ids.length}개(${partsOf(op.part_ids, name)}) · ${DIMENSION_NAMES[op.field] ?? op.field} ${op.from_value}mm → ${op.to_value}mm`
    case 'equipment_spec':
      return `${head} · ${op.part_ids.length}개(${partsOf(op.part_ids, name)}) · ${op.from_spec_id} → ${op.to_spec_id}`
    case 'remove_part':
      return `${head} · ${op.part_ids.length}개(${partsOf(op.part_ids, name)})`
    case 'add_part':
      return `${head} · ${op.spec_id} 수량 ${op.qty} · 블록 ${blockLabel({ block_id: op.block_id, name: '' }).code}`
    case 'reroute_pipe':
      return `${head} · 빼는 스풀 ${op.removed_part_ids.length}개 · 새 스풀 ${op.added_spool_spec_ids.length}개 · 관통 판 ${op.crosses_part_ids.length}개`
    case 'add_penetration':
      return `${head} · ${name(op.plate_part_id)} · 지름 ${op.diameter_mm}mm`
    default:
      return head
  }
}

export interface ChangeSection {
  ops: string[]
  /** 변경 원인(미입력이면 '미입력'). */
  cause: string
  /** 원문(비서·문서로 넣은 글, 없으면 null). */
  rawText: string | null
  /** 담당자 의견(이 개정 검토 요청의 사유, 없으면 null). */
  opinion: string | null
}

/** 이 개정의 마지막 검토 요청 감사 줄(없으면 undefined). */
function reviewEntry(audit: readonly AuditEntry[], revision: number): AuditEntry | undefined {
  return audit.filter((e) => e.revision === revision && e.action === 'request_review').sort((a, b) => b.seq - a.seq)[0]
}

function changeSection(result: AnalysisResult, audit: readonly AuditEntry[], revision: number): ChangeSection {
  const { change } = result.request
  const name = namer(result)
  return {
    ops: change.ops.map((op) => opLine(op, name)),
    cause: causeName(change.cause),
    rawText: change.raw_text?.trim() || null,
    opinion: reviewEntry(audit, revision)?.detail.reason?.trim() || null,
  }
}

/** 대상 블록: 중량 변화의 블록(1.34.0) → 연결 추적의 블록(1.23.0) 순으로, 코드만 ', '로. 모르면 '—'. */
export function targetBlocks(result: Pick<AnalysisResult, 'weight_change' | 'trace'>): string {
  const fromWeight = (result.weight_change?.blocks ?? []).flatMap((b) => (b.block_id ? [b.block_id] : []))
  const fromTrace = (result.trace ?? []).flatMap((chain) => (chain.block ? [chain.block.entity_id] : []))
  const ids = [...new Set(fromWeight.length > 0 ? fromWeight : fromTrace)].sort()
  return ids.length > 0 ? ids.map((id) => blockLabel({ block_id: id, name: '' }).code).join(', ') : '—'
}

// ---------- 판정과 핵심 수치 ----------

export interface FigureRow {
  label: string
  value: string
  detail: string | null
  caution: string | null
}

/**
 * 핵심 수치 표(문서라 해당 없음도 줄로): (계약 1.35.0 구분이 있으면) 추가 공수(MH · ≈금액) → 추가 재료비 → 총변경비용(범위,
 * = 두 금액 합) → 결정 기한(날짜 · D-n) → 구역 출구 지연 → 이미 발주된 품목 → (있으면) 늘어난 인도 지연. 값은 상세 카드
 * (costHead·keyNumbers·orderedCard)와 같다.
 */
export function figureRows(result: AnalysisResult): FigureRow[] {
  const cards = keyNumbers(result)
  const card = (id: string) => cards.find((c) => c.id === id)
  const head = costHead(result)
  const total = card('total')
  const deadline = card('deadline')
  const { kind, last_day: lastDay } = result.timing.deadline
  const ordered = orderedCard(result)
  const exit = card('exit')
  const split: FigureRow[] = head
    ? [
        head.labor
          ? {
              label: '추가 공수',
              value: `${head.labor.hours} · ${head.labor.money}`,
              detail: [head.labor.works, head.labor.range ? `범위 ${head.labor.range}` : null].filter(Boolean).join(' · ') || null,
              caution: null,
            }
          : { label: '추가 공수', value: '없음', detail: null, caution: null },
        head.material
          ? {
              label: '추가 재료비',
              value: head.material.value,
              detail: [head.material.parts, head.material.range ? `범위 ${head.material.range}` : null].filter(Boolean).join(' · ') || null,
              caution: null,
            }
          : { label: '추가 재료비', value: '없음', detail: null, caution: null },
      ]
    : []
  const totalDetail = head ? [total?.detail, `= ${head.total.sum}`].filter(Boolean).join(' · ') : (total?.detail ?? null)
  const rows: FigureRow[] = [
    ...split,
    { label: '총변경비용', value: total?.value ?? '—', detail: totalDetail, caution: null },
    {
      label: '결정 기한',
      value: kind === 'none_in_horizon' ? '기간 안 없음' : `${formatDay(lastDay)} · ${deadline?.value ?? ''}`,
      detail: deadline?.detail ?? null,
      caution: deadline?.caution ?? null,
    },
    exit
      ? { label: '구역 출구 지연', value: exit.value, detail: exit.detail ?? null, caution: exit.caution ?? null }
      : { label: '구역 출구 지연', value: '0일', detail: '지연 없음', caution: null },
    ordered
      ? { label: '이미 발주된 품목', value: ordered.value, detail: ordered.detail ?? null, caution: ordered.caution ?? null }
      : { label: '이미 발주된 품목', value: '없음', detail: '바뀌는 발주 품목 중 발주 나간 것 없음', caution: null },
  ]
  const delivery = card('delivery')
  if (delivery) {
    rows.push({ label: delivery.label, value: delivery.value, detail: delivery.detail ?? null, caution: delivery.caution ?? null })
  }
  return rows
}

// ---------- 영향 범위 ----------

const SCOPE_TYPES = [
  ['block', '블록'],
  ['po_line', '발주 품목'],
  ['activity', '공정'],
  ['drawing', '도면'],
] as const

export interface ScopeSummary {
  counts: { label: string; count: number }[]
  /** 2차 영향(근거 경로 두 단계 이상) 수. */
  secondary: number
  /** 주요 2차 영향(심각도 높은 순 4개): '이름 — 영향 종류'. */
  highlights: string[]
}

/** 영향 범위 요약: 블록·발주 품목·공정·도면 수(엔터티 수, 영향 결과 그대로)와 주요 2차 영향. */
export function scopeSummary(result: Pick<AnalysisResult, 'impacts' | 'graph'>): ScopeSummary {
  const name = namer(result)
  const counts = SCOPE_TYPES.map(([type, label]) => ({
    label,
    count: new Set(result.impacts.filter((i) => i.entity_type === type).map((i) => i.entity_id)).size,
  }))
  const second = result.impacts.filter((i) => i.path.length >= 2)
  const ranked = [...second].sort(
    (a: Impact, b: Impact) =>
      SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.entity_id.localeCompare(b.entity_id),
  )
  const highlights = [
    ...new Set(ranked.map((i) => `${name(i.entity_id)} — ${IMPACT_NAMES[i.impact_type] ?? i.impact_type}`)),
  ].slice(0, 4)
  return { counts, secondary: second.length, highlights }
}

// ---------- 결재란 ----------

export interface SignCell {
  role: string
  /** 결재한 사람(없으면 null — 빈칸). */
  name: string | null
  /** '검토 요청' · '승인' · '반려' · '보류' · '담당자 처리'(없으면 null). */
  mark: string | null
  /** 팀장 전결. */
  proxy: boolean
  /** KST 날짜(없으면 ''). */
  day: string
}

const STEP_ROLE = { part_lead: '파트장', team_lead: '팀장', executive: '본부장' } as const
const DECISION_MARK: Partial<Record<AuditEntry['action'], string>> = { approve: '승인', reject: '반려', hold: '보류' }

const empty = (role: string): SignCell => ({ role, name: null, mark: null, proxy: false, day: '' })

/**
 * 결재란 네 칸(담당 · 파트장 · 팀장 · 본부장): 이 개정의 마지막 검토 요청(담당)과 그 검토의 단계별 마지막 결정(승인·반려·
 * 보류, 팀장 전결 표시)을 감사 줄 그대로. 기록이 없으면 빈칸. 무비용 담당자 처리(settle)면 담당 칸에 '담당자 처리'.
 * 단계가 없는 옛 검토(판 3까지)의 결정은 팀장 칸(docs/records.md(기록·결재) 4절 — 팀장 한 단계로 읽음).
 */
export function signCells(audit: readonly AuditEntry[], revision: number): SignCell[] {
  const cells: Record<'member' | keyof typeof STEP_ROLE, SignCell> = {
    member: empty('담당'),
    part_lead: empty(STEP_ROLE.part_lead),
    team_lead: empty(STEP_ROLE.team_lead),
    executive: empty(STEP_ROLE.executive),
  }
  const review = reviewEntry(audit, revision)
  const settled = audit.filter((e) => e.revision === revision && e.action === 'settle').sort((a, b) => b.seq - a.seq)[0]
  const opener = review ?? settled
  if (opener) {
    cells.member = {
      role: '담당',
      name: opener.actor.name,
      mark: review ? '검토 요청' : '담당자 처리',
      proxy: false,
      day: kstDay(opener.at),
    }
  }
  if (review) {
    const decisions = audit
      .filter((e) => e.detail.review_seq === review.seq && DECISION_MARK[e.action])
      .sort((a, b) => a.seq - b.seq)
    for (const entry of decisions) {
      const step = entry.detail.step ?? 'team_lead'
      cells[step] = {
        role: STEP_ROLE[step],
        name: entry.actor.name,
        mark: DECISION_MARK[entry.action] ?? null,
        proxy: entry.detail.proxy,
        day: kstDay(entry.at),
      }
    }
  }
  return [cells.member, cells.part_lead, cells.team_lead, cells.executive]
}

// ---------- 꼬리 ----------

/** 출처 표기: '합성 데이터 · Ripple 분석 결과'(실데이터면 'Ripple 분석 결과'). */
export function sourceLine(synthetic: boolean): string {
  return synthetic ? `합성 데이터 · ${SOURCE_NOTE}` : SOURCE_NOTE
}

/** CSS 글(content: "…") 안에 넣을 수 있게 따옴표·역빗금·줄바꿈을 막는다. */
export function cssString(text: string): string {
  return `"${text.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\n\r]/g, ' ')}"`
}

/**
 * 인쇄 쪽 머리·꼬리(@page 여백 상자, Chromium 131+): 위 오른쪽 '설계변경 검토서 · ECN · 개정', 아래 왼쪽 출처, 아래 오른쪽
 * 'n / 전체 쪽'. 여백 상자를 모르는 브라우저는 무시하고 본문 꼬리의 출처 줄만 남는다.
 */
export function pageCss(head: string, foot: string): string {
  return [
    '@page {',
    `  @top-right { content: ${cssString(head)}; font-size: 8pt; color: #444; }`,
    `  @bottom-left { content: ${cssString(foot)}; font-size: 8pt; color: #444; }`,
    '  @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #444; }',
    '}',
  ].join('\n')
}

// ---------- 문서 한 벌 ----------

export interface SheetModel {
  change: ChangeSection
  figures: FigureRow[]
  scope: ScopeSummary
  signs: SignCell[]
  /** 대상 블록 코드(', '로). */
  blocks: string
  /** 작성일 = 이 개정을 기록한 시각(KST). */
  writtenAt: string
  /** 결재선(이 검토에 고정한 결재선, 없으면 null). */
  line: string | null
  /** 1.34.0 블록별 강재 중량 변화(이 판 전 기록이면 null). */
  weight: AnalysisResult['weight_change'] | null
}

const LINE_NAMES = { part_lead: '파트장', team_lead: '팀장', executive: '본부장' } as const

/** 기록 본문의 분석 결과 + 그 설계변경의 감사 줄 → 검토서 전용 값. recordedAt = 그 개정의 기록 시각. */
export function sheetOf(result: AnalysisResult, audit: readonly AuditEntry[], revision: number, recordedAt: string): SheetModel {
  const review = reviewEntry(audit, revision)
  const steps = review?.detail.steps ?? []
  return {
    change: changeSection(result, audit, revision),
    figures: figureRows(result),
    scope: scopeSummary(result),
    signs: signCells(audit, revision),
    blocks: targetBlocks(result),
    writtenAt: kstStamp(recordedAt),
    line: steps.length > 0 ? steps.map((step) => LINE_NAMES[step]).join(' → ') : null,
    weight: result.weight_change ?? null,
  }
}