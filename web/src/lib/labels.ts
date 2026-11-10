// 화면 이름표(명사형). 값은 계약(ripple/contracts)의 열거형과 1:1이다.
import type { ImpactType, Severity } from '@/api/client'

export const IMPACT_NAMES: Record<ImpactType, string> = {
  modify_part: '부재 수정',
  po_change: '발주 변경·취소',
  reorder: '새 규격 발주',
  po_hold: '발주 보류',
  rework: '블록 재작업',
  taper: '테이퍼 가공',
  weld_recheck: '용접 재검토',
  collar_resize: '칼라 치수 변경',
  drawing_revision: '도면 개정',
  schedule_delay: '예상 일정 지연',
  delivery_delay: '예상 인도 지연',
  reallocate_stock: '잉여 자재 전용',
  needs_confirmation: '확인 필요',
}

export const ENTITY_NAMES: Record<string, string> = {
  ship: '선박',
  zone: '구역',
  block: '블록',
  part: '부재',
  po: '발주',
  po_line: '발주 품목',
  stock: '재고',
  activity: '공정',
  drawing: '도면',
}

export const RELATION_NAMES: Record<string, string> = {
  part_of: '소속',
  supplied_by: '공급',
  butt_weld: '맞대기 용접',
  fillet_weld: '필릿 용접',
  penetration: '관통',
  support: '지지',
  pipe_joint: '배관 연결',
  drawn_in: '도면',
  consumed_by: '소비 공정',
  precedes: '선후행',
  same_spec: '같은 규격',
}

export const SEVERITY_NAMES: Record<Severity, string> = { high: '높음', medium: '보통', low: '낮음', info: '정보' }
export const SEVERITY_RANK: Record<Severity, number> = { info: 0, low: 1, medium: 2, high: 3 }

export const OP_NAMES: Record<string, string> = {
  thickness: '두께 변경',
  grade: '강종 변경',
  dimension: '치수 변경',
  add_part: '부재 추가',
  remove_part: '부재 삭제',
  reroute_pipe: '배관 경로 변경',
  equipment_spec: '장비 사양 변경',
  add_penetration: '관통부 추가',
}

export const UNRESOLVED_NAMES: Record<string, string> = {
  po_state: '발주 단계 판단 불가',
  block_stage: '블록 단계 판단 불가',
  connection: '연결 확인 필요',
  delivery: '인도 지연 계산 불가',
  strength_inputs: '강도 입력 부족',
}

export const ROLE_NAMES: Record<string, string> = { target: '바꾸는 부재', removed: '빼는 부재', new: '새 부재' }

/** 규칙 한 줄 설명(docs/engine.md(전파) 5절). */
export const RULE_TITLES: Record<string, string> = {
  'R-T01': '규격이 바뀐 부재의 발주 품목',
  'R-M02': '빼는 부재의 발주 품목',
  'R-T02': '맞댄 판의 두께 차 → 테이퍼',
  'R-T03': '필릿 용접 상대의 용접 사양',
  'R-T04': '관통하는 배관의 칼라·슬리브',
  'R-P01': '장비 연결 규격 → 인접 배관',
  'R-P02': '새 배관 경로가 지나는 판',
  'R-P03': '빼는 스풀을 받치던 서포트',
  'R-M01': '같은 규격 재고·수요로 전용',
  'R-B01': '착수한 블록의 재작업',
  'R-D01': '부재가 그려진 도면',
  'R-X01': '연결 정보가 없어 계산에서 뺌',
  'R-S01': '자재 입고 지연 → 공정 지연',
  'R-H01': '발주 보류 권고',
  'R-L01': '인도 지연(지체상금, 선주 요청이면 인도일 조정)',
}

/** 노드 속성 이름(ripple/engine/describe.py가 내는 키). */
export const ATTR_NAMES: Record<string, string> = {
  kind: '종류',
  spec_id: '규격',
  thickness_mm: '두께(mm)',
  grade: '강종',
  system: '계통',
  block_id: '블록',
  zone_id: '구역',
  steel_weight_t: '강재 중량(t)',
  supplier_id: '협력사',
  planned_order_date: '계획 발주일',
  lead_time_days: '리드타임(일)',
  qty: '수량',
  unit_price_krw: '단가(원)',
  planned_start: '계획 착수일',
  duration_days: '기간(일)',
  actual_start: '실제 착수일',
  discipline: '분야',
  reserved_block_id: '예약 블록',
}

export const PART_KIND_NAMES: Record<string, string> = {
  plate: '판',
  stiffener: '보강재',
  bracket: '브라켓',
  collar: '칼라',
  pipe_spool: '배관 스풀',
  valve: '밸브',
  pipe_support: '서포트',
  equipment: '장비',
}

/** 규격 분류(리드타임 파라미터의 분류) 이름. */
export const MATERIAL_NAMES: Record<string, string> = {
  plate: '판재',
  section: '형강',
  pipe: '배관',
  valve: '밸브',
  fitting: '배관 부속',
  equipment: '장비',
}

export const materialName = (category: string): string => MATERIAL_NAMES[category] ?? category

/** 속성 값을 읽기 쉽게: 종류는 한글, 숫자는 천 단위 구분. */
export function attrValue(key: string, value: string | number | boolean): string {
  // 종류는 부재(판·보강재…)와 공정(탑재·대조립…)이 같은 키를 쓴다
  if (key === 'kind' && typeof value === 'string') return PART_KIND_NAMES[value] ?? ACTIVITY_NAMES[value] ?? value
  if (typeof value === 'number') return value.toLocaleString('ko-KR')
  return String(value)
}

export const nameOf = (table: Record<string, string>, key: string): string => table[key] ?? key

export const VERDICT_NAMES: Record<string, string> = { approve: '승인 가능', review: '검토 필요', warn: '경고' }

/** 발주 단계(진행 순서). */
export const PO_STATUS_NAMES: Record<string, string> = {
  not_ordered: '미발주',
  ordered: '발주',
  material_secured: '자재 확보',
  in_fabrication: '제작',
  received: '입고',
  processed: '가공',
}
export const PO_STATUS_ORDER = Object.keys(PO_STATUS_NAMES)

export const ACTIVITY_NAMES: Record<string, string> = {
  sub_assembly: '소조립',
  panel: '판넬조립',
  assembly: '대조립',
  pre_outfitting: '선행의장',
  pre_painting: '선행도장',
  pre_erection: 'PE',
  erection: '탑재',
  exit: '구역 출구',
  launch: '진수',
  sea_trial: '시운전',
  delivery: '인도',
}

/** 블록 단계(엔진 BlockStage, 진행 순서). 공정 이름과 같고 착수 전 두 단계가 더 있다. */
export const BLOCK_STAGE_NAMES: Record<string, string> = {
  not_started: '미착수',
  steel_received: '강재 입고',
  sub_assembly: '소조립',
  panel: '판넬조립',
  assembly: '대조립',
  pre_outfitting: '선행의장',
  pre_painting: '선행도장',
  pre_erection: 'PE',
  erected: '탑재',
}

/** 협력사 구분(계약 SupplierKind): 기자재 공급사 · 사외 협력사 · 사외 블록 제작. 사내 협력사(작업반)는 따로. */
export const SUPPLIER_KIND_NAMES: Record<string, string> = {
  steel: '기자재 공급사(강재)',
  pipe: '기자재 공급사(배관재)',
  equipment: '기자재 공급사(밸브·장비)',
  block: '사외 블록 제작',
  outfitting: '기자재 공급사(의장품)',
  parts: '사외 협력사(단품)',
}

/** 블록 형상(난이도 계수 입력). */
export const BLOCK_SHAPE_NAMES: Record<string, string> = { flat: '평블록', curved: '곡블록', bow_stern: '선수미 블록' }

/** 호선을 뺀 마지막 코드: "S-001:ZCT" → "ZCT". */
export function codeOf(id: string): string {
  return id.slice(id.lastIndexOf(':') + 1)
}

/** 구역 이름: 지도의 구역 이름(예: 화물탱크 구역), 없으면 코드("S-001:ZCT" → "ZCT"). */
export function zoneName(exit: { zone_id: string; zone_name?: string | null }): string {
  return exit.zone_name || codeOf(exit.zone_id)
}

/** 공정 ID → 이름: "S-001:T31C:erection" → "T31C 탑재", "S-001:ZCT:exit" → "ZCT 구역 출구", "S-001:delivery" → "인도". */
export function activityName(id: string): string {
  const parts = id.split(':')
  const kind = parts[parts.length - 1]
  const name = ACTIVITY_NAMES[kind] ?? kind
  return parts.length >= 3 ? `${parts[parts.length - 2]} ${name}` : name
}
