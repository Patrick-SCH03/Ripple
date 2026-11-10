// 소개 화면의 실제 업무 화면 그림(public/landing, 합성 데이터)과 그림 위 강조 자리. 그림은 시연 서버에 빠른 로그인으로 들어가
// 1배·2배 webp로 찍었다(예시 기준일 = example.ts SHOWCASE_DAY): 판단 요약·핵심 수치·결정 기한 카드·비용 탭·중량 변화·추가손실
// 곡선·대안·영향 지도(2D)·3D 배치는 담당자가 연 ECN-D-0119(기록 전), 비서 칸은 예시 문장 1(3번 탱크 횡격벽 판 두께 변경 — 다른
// 요청), 결재함은 시연 기록 시드 위에서 담당자가 ECN-D-0119를 검토 요청하고 파트장이 승인한 뒤 팀장 화면(팀장 차례 4건 + 다른
// 단계에서 기다리는 건(전결 가능) 2건), 검토서는 같은 개정을 팀장·본부장까지 승인한 뒤의 A4 문서. 3D 물결 전파는 같은 3D 화면을
// 녹화한 4초 반복 영상(소리 없음)이다. 자리는 찍을 때 화면 요소의 사각형을 잰 값이다(그림의 CSS 픽셀 기준). 그림 속 숫자는
// PICTURED·alt에 적고 검사(captures.test.ts)가 example.json과 대조한다. 다시 찍는 방법은 docs/operations.md 소개 단락.
import type { MapStepKey } from './mapSteps'

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface Capture {
  /** 확장자 없는 주소: `${src}.webp`(1배) · `${src}@2x.webp`(2배) · 더 큰 배율은 scales에. */
  src: string
  /** 1배 크기(CSS 픽셀). */
  width: number
  height: number
  alt: string
  /** 있는 배율(기본 1·2). 확대해서 보는 그림은 더 큰 배율을 둔다(첫 화면 3D 4배 · 영향 지도 3배). */
  scales?: readonly number[]
}

/** 그림 판(찍은 날, example.ts SHOWCASE_DAY와 같음 — 검사). 그림은 하루 캐시(Caddyfile)라 다시 찍으면 주소를 바꿔
 *  옛 그림 위에 새 강조 자리가 얹히지 않게 한다. */
export const SHOT_VERSION = '2026-11-04'

/** 있는 배율(작은 것부터). */
function scalesOf(shot: Capture): readonly number[] {
  return shot.scales ?? [1, 2]
}

/** 그림 주소(배율별 webp, 판 붙임). */
export function shotUrl(shot: Capture, scale = 1): string {
  return `${shot.src}${scale === 1 ? '' : `@${scale}x`}.webp?v=${SHOT_VERSION}`
}

/** 가장 큰 배율의 주소(확대해서 보는 곳). */
export function largestUrl(shot: Capture): string {
  const all = scalesOf(shot)
  return shotUrl(shot, all[all.length - 1])
}

/** srcset: 배율마다 폭(w) — 브라우저가 표시 크기 × 기기 배율에 맞는 것을 고른다. */
export function srcSet(shot: Capture): string {
  return scalesOf(shot)
    .map((scale) => `${shotUrl(shot, scale)} ${shot.width * scale}w`)
    .join(', ')
}

/** 그림 안 사각형 → 그림 크기 비율(%) 위치(어느 폭에서도 같은 곳). */
export function percentBox(shot: Capture, rect: Rect): { left: string; top: string; width: string; height: string } {
  return {
    left: `${(rect.x / shot.width) * 100}%`,
    top: `${(rect.y / shot.height) * 100}%`,
    width: `${(rect.w / shot.width) * 100}%`,
    height: `${(rect.h / shot.height) * 100}%`,
  }
}

/* ---------- 첫 화면: 3D 배치(전체 시점 — 스크롤에 따라 1.8배 확대) + 검토서 ---------- */

export const SHIP_WHOLE_SHOT: Capture = {
  src: '/landing/ship-whole',
  width: 1000,
  height: 500,
  scales: [1, 2, 4],
  alt: '3D 배치 전체 시점: 가상 수에즈맥스 원유운반선 선체의 블록 배치 위에 영향 블록 B31P·L31C·T31C·S31P·D31C를 높음(빨강)으로 칠하고 탑재 선행·맞대기 용접 이음 점선(시연 합성 지도)',
}

export const DEADLINE_CARD_SHOT: Capture = {
  src: '/landing/deadline-card',
  width: 1001,
  height: 325,
  alt: '결정 기한 카드: D-7, 결재 올릴 기한 안내, 늦추면 일정 악화, 하루 늦으면 +1,867만원 작은 곡선과 확정일을 11월 11일(수)로 단추(합성 데이터)',
}

export const REPORT_SHOT: Capture = {
  src: '/landing/report',
  width: 794,
  height: 884,
  alt: 'A4 설계변경 검토서 첫머리: 문서 머리(ECN 번호·호선·대상 블록·작성자), 1. 변경 내용·사유, 2. 판정과 핵심 수치(추가 공수 807 MH ≈ 4,007만원 · 추가 재료비 327만원 · 총변경비용 4,334만원 · 결정 기한 11월 11일(수) D-7)(합성 데이터)',
}

/** 검토서 그림의 강조 자리: 문서 머리, 판정과 핵심 수치 표. */
export const REPORT_MARKS: { facts: Rect; numbers: Rect } = {
  facts: { x: 58, y: 136, w: 678, h: 149 },
  numbers: { x: 58, y: 588, w: 678, h: 291 },
}

export const REPORT_SIGN_SHOT: Capture = {
  src: '/landing/report-sign',
  width: 714,
  height: 170,
  scales: [1, 2, 3],
  alt: '검토서 8. 결재란: 담당 김설계(검토 요청) · 파트장 이파트장 · 팀장 박팀장 · 본부장 최본부장(승인)과 날짜(합성 데이터)',
}

/** 같은 검토서의 머리만(제목 · ECN 번호 · 대상 블록 · 작성일 줄) — 첫 화면 장면 5단계 카드에서 결재란과 함께 크게. */
export const REPORT_HEAD_SHOT: Capture = {
  src: '/landing/report-head',
  width: 714,
  height: 165,
  scales: [1, 2, 3],
  alt: '설계변경 검토서 머리: 제목, B31P 판 두께 17.0→20.0mm (3장), ECN 번호 ECN-D-0119 · 개정 1, 호선 S-001, 대상 블록 B31P, 작성자 김설계(담당자)(합성 데이터)',
}

/* ---------- 상세 화면: 판단 요약 ---------- */

export const SUMMARY_SHOT: Capture = {
  src: '/landing/summary',
  width: 1059,
  height: 1395,
  alt: 'ECN-D-0119 상세 위쪽: 판정 경고와 이유 한 줄, 결재 띠, 구역 이동 막대(판단 요약 · 영향 범위 · 할 일 · 근거 상세), 판단 요약 구역의 변경 내용 3행과 더 저렴한 대안 안내, 첫 줄 총변경비용 4,334만원 · 추가 공수 807 MH ≈ 4,007만원 · 추가 재료비 327만원(이미 발주 1건), 다음 줄 결정 기한 D-7 · 구역 출구 예상 최대 지연 9일(합성 데이터)',
}

/** 판단 요약 그림의 강조 자리: 구역 이동 막대, 첫 줄(총변경비용 · 추가 공수 · 추가 재료비), 총변경비용 카드, 결정 기한·구역 출구 카드. */
export const SUMMARY_MARKS: { nav: Rect; keys: Rect; total: Rect; timing: Rect } = {
  nav: { x: 8, y: 328, w: 1043, h: 40 },
  keys: { x: 29, y: 756, w: 1001, h: 134 },
  total: { x: 29, y: 756, w: 326, h: 134 },
  timing: { x: 29, y: 903, w: 1001, h: 463 },
}

export const COST_SHOT: Capture = {
  src: '/landing/cost',
  width: 585,
  height: 1061,
  alt: '비용 탭: 공수 묶음(807 MH, 4,007만원 — 블록 재작업·테이퍼 가공·도면 개정·용접 재검토 줄마다 MH)과 재료비 묶음(327만원 — 자재 차이 · 구매 줄), 아래 합계 4,334만원(합성 데이터)',
}

/** 비용 탭 그림의 강조 자리: 공수 소계, 재료비 소계, 합계. */
export const COST_MARKS: { labor: Rect; material: Rect; total: Rect } = {
  labor: { x: 0, y: 2, w: 585, h: 73 },
  material: { x: 0, y: 643, w: 585, h: 73 },
  total: { x: 0, y: 981, w: 585, h: 76 },
}

export const WEIGHT_SHOT: Capture = {
  src: '/landing/weight',
  width: 613,
  height: 201,
  alt: '중량 변화 표: B31P No.3 COT 이중저 좌 블록 원래 3.89t → 새 4.57t, 차이 +0.69t, 부재 3개(합성 데이터)',
}

/* ---------- 영향 범위: 3D 배치 · 2D 영향 지도 ---------- */

export const SHIP_SHOT: Capture = {
  src: '/landing/ship3d',
  width: 1600,
  height: 900,
  alt: '3D 배치 전체 화면(화물창 시점): 바꾸는 부재가 있는 B31P 블록과 맞대기 용접으로 이어진 L31C, 탑재 선행으로 이어진 T31C·S31P(1차)·D31C(2차) 블록을 높음(빨강)으로 칠하고 이음 점선, 위 막대에 범례·시점 단추, 오른쪽 영향 24건과 영향 목록(합성 데이터)',
}

/** 3D 물결 전파 반복 영상(SHIP_SHOT과 같은 화면 · 같은 비율, 4초 · 소리 없음). 정지 그림은 SHIP_SHOT. */
export const SHIP_VIDEO = {
  webm: `/landing/ship-wave.webm?v=${SHOT_VERSION}`,
  mp4: `/landing/ship-wave.mp4?v=${SHOT_VERSION}`,
  label: '3D 배치 물결 전파: 바꾸는 부재가 있는 B31P 블록에서 고리가 퍼지고 영향이 번진 순서대로 블록이 밝아지며 이음면 점선이 흐름(실제 화면 녹화, 합성 데이터)',
}

/** 3D 그림의 강조 자리: 바꾸는 부재 블록, 이웃 블록, 시점 단추, 영향 목록. */
export const SHIP_MARKS: { changed: Rect; neighbor: Rect; views: Rect; list: Rect } = {
  changed: { x: 775, y: 694, w: 117, h: 41 },
  neighbor: { x: 380, y: 498, w: 151, h: 39 },
  views: { x: 396, y: 34, w: 229, h: 44 },
  list: { x: 1072, y: 210, w: 512, h: 682 },
}

export const MAP_SHOT: Capture = {
  src: '/landing/map',
  width: 2700,
  height: 471,
  scales: [1, 2, 3],
  alt: '영향 지도 전체 화면: 바뀐 판 3장에서 용접 재검토·테이퍼 가공 묶음, B31P 블록, 발주 PO-0037 #1, 도면 개정, 이웃 L31C 블록으로 이어지고 B31P 소조립부터 탑재까지 공정, 그 뒤 탑재 선행으로 T31C·S31P·L31C 탑재와 D31C 탑재까지 이어짐(합성 데이터)',
}

/** 영향 지도 그림 속 카드 자리(지도 노드 id). */
const MAP_NODES: Record<string, Rect> = {
  'S-001:B31P-PL-002': { x: 93, y: 168, w: 181, h: 65 },
  'S-001:B31P-PL-005': { x: 93, y: 382, w: 181, h: 65 },
  'S-001:B31P-PL-007': { x: 93, y: 24, w: 181, h: 65 },
  'DWG-B31P-H01@A': { x: 326, y: 338, w: 181, h: 65 },
  'PO-0037#1': { x: 326, y: 264, w: 181, h: 65 },
  'S-001:B31P': { x: 326, y: 191, w: 181, h: 65 },
  'group:1:part:taper:medium': { x: 326, y: 112, w: 181, h: 71 },
  'group:1:part:weld_recheck:low': { x: 326, y: 33, w: 181, h: 71 },
  'DWG-L31C-H01@A': { x: 559, y: 182, w: 181, h: 65 },
  'S-001:B31P:sub_assembly': { x: 559, y: 301, w: 181, h: 65 },
  'S-001:L31C': { x: 559, y: 109, w: 181, h: 65 },
  'S-001:B31P:panel': { x: 793, y: 279, w: 181, h: 65 },
  'S-001:B31P:assembly': { x: 1026, y: 279, w: 181, h: 65 },
  'S-001:B31P:pre_outfitting': { x: 1259, y: 279, w: 181, h: 65 },
  'S-001:B31P:pre_painting': { x: 1493, y: 279, w: 181, h: 65 },
  'S-001:B31P:pre_erection': { x: 1726, y: 279, w: 181, h: 65 },
  'S-001:B31P:erection': { x: 1959, y: 279, w: 181, h: 65 },
  'S-001:L31C:erection': { x: 2192, y: 316, w: 181, h: 65 },
  'S-001:S31P:erection': { x: 2192, y: 242, w: 181, h: 65 },
  'S-001:T31C:erection': { x: 2192, y: 169, w: 181, h: 65 },
  'S-001:D31C:erection': { x: 2426, y: 316, w: 181, h: 65 },
}

/** 단계마다 확대할 카드들. */
const MAP_FOCUS: Record<MapStepKey, string[]> = {
  change: ['S-001:B31P-PL-002', 'S-001:B31P-PL-005', 'S-001:B31P-PL-007'],
  weld: ['group:1:part:taper:medium', 'group:1:part:weld_recheck:low'],
  block: ['S-001:B31P'],
  neighbor: ['group:1:part:taper:medium', 'S-001:L31C'],
  drawings: ['DWG-B31P-H01@A', 'DWG-L31C-H01@A'],
  po: ['PO-0037#1'],
  erection: [
    'S-001:B31P:sub_assembly',
    'S-001:B31P:panel',
    'S-001:B31P:assembly',
    'S-001:B31P:pre_outfitting',
    'S-001:B31P:pre_painting',
    'S-001:B31P:pre_erection',
    'S-001:B31P:erection',
    'S-001:T31C:erection',
    'S-001:S31P:erection',
    'S-001:L31C:erection',
    'S-001:D31C:erection',
  ],
}

/** 여러 사각형을 감싸는 사각형(가장자리 여백 pad). */
export function union(rects: Rect[], pad = 0): Rect {
  const x = Math.min(...rects.map((r) => r.x)) - pad
  const y = Math.min(...rects.map((r) => r.y)) - pad
  const right = Math.max(...rects.map((r) => r.x + r.w)) + pad
  const bottom = Math.max(...rects.map((r) => r.y + r.h)) + pad
  return { x, y, w: right - x, h: bottom - y }
}

/** 단계의 확대 자리(카드들 + 여백). 카드 자리를 모르면 null(전체 지도). */
export function mapFocus(key: MapStepKey): Rect | null {
  const rects = MAP_FOCUS[key].map((id) => MAP_NODES[id]).filter(Boolean)
  return rects.length ? union(rects, 10) : null
}

/* ---------- 결정 기한 · 대안 ---------- */

export const CURVE_SHOT: Capture = {
  src: '/landing/curve',
  width: 1001,
  height: 864,
  alt: '추가손실 곡선 탭: 1월 3일(일)까지 확정일별 추가손실 계단 그래프와 결정 기한 점선, 아래 비용이 바뀌는 날 표(11월 11일(수)까지 0원, 11월 12일(목) 1,867만원)(합성 데이터)',
}

/** 곡선 그림의 강조 자리: 결정 기한 점선(이름 포함), 다음 날 늘어나는 줄. */
export const CURVE_MARKS: { deadline: Rect; stepRow: Rect } = {
  deadline: { x: 99, y: 51, w: 73, h: 248 },
  stepRow: { x: 0, y: 735, w: 1001, h: 121 },
}

export const OPTIONS_SHOT: Capture = {
  src: '/landing/options',
  width: 1001,
  height: 493,
  alt: '대안 탭: 최저 비용 조합(판 두께 대신 보강재 추가)과 요청안·대안 표(판정·출구 예상 지연·결정 기한·총변경비용), 아래 접힌 대안 안내(합성 데이터)',
}

/** 대안 그림의 강조 자리: 최저 비용 조합, 접힌 대안 안내 줄. */
export const OPTIONS_MARKS: { best: Rect; note: Rect } = {
  best: { x: 0, y: 0, w: 1001, h: 184 },
  note: { x: 0, y: 463, w: 1001, h: 26 },
}

/* ---------- 결재 · AI 비서 ---------- */

export const APPROVAL_SHOT: Capture = {
  src: '/landing/approval',
  width: 1200,
  height: 1175,
  alt: '결재선(파트장 → 팀장 → 본부장) 가운데 팀장 단계의 결재·현황 결재함: 결정 기한이 급한 순으로 네 건, 줄마다 결재선 진행(파트장 승인 → 팀장 차례 → 본부장)과 총변경비용·미루면 늘어나는 금액(ECN-D-0119는 D-7 · 4,334만원 · 미루면 11월 12일(목)부터 +1,867만원), 아래 다른 단계에서 기다리는 건(전결 가능) 2건(합성 데이터)',
}

/** 결재 그림의 강조 자리: 맨 위 줄의 D-n 상자, ECN-D-0119 줄의 '미루면'과 결재선 진행, 전결 가능 묶음. */
export const APPROVAL_MARKS: { due: Rect; later: Rect; line: Rect; proxy: Rect } = {
  due: { x: 41, y: 295, w: 112, h: 64 },
  later: { x: 790, y: 600, w: 270, h: 27 },
  line: { x: 169, y: 631, w: 342, h: 28 },
  proxy: { x: 24, y: 883, w: 1152, h: 272 },
}

export const ASSISTANT_SHOT: Capture = {
  src: '/landing/assistant',
  width: 400,
  height: 812,
  alt: 'AI 비서 칸: 문장으로 적은 판 두께 변경 요청을 두께 변경·대상 판·15→17mm·강도 보강으로 풀어 쓰고, 판정 경고와 총변경비용·결정 기한, 협력사 알림 초안 4건을 보여 줌(합성 데이터)',
}

/**
 * 그림에 찍힌 예시 값(찍은 날의 화면 그대로 — ECN-D-0119, 판단 요약·핵심 수치·결정 기한 카드·곡선·비용 탭·중량·결재함·검토서).
 * 검사(captures.test.ts)가 예시 기준일로 옮긴 example.json(지금 엔진)과 같은지, alt·링크 미리보기 글(index.html og:image:alt)의
 * 숫자가 이 값뿐인지 본다. 엔진·규칙·파라미터가 바뀌어 example.json이 달라지면 검사가 실패한다 → 그림을 다시 찍고 이 값·alt·
 * SHOWCASE_DAY를 함께 고친다.
 */
export const PICTURED = {
  /** 찍은 날(그날의 업무상 오늘) = example.ts SHOWCASE_DAY. */
  day: '2026-11-04',
  total: '4,334만원',
  range: '1,236만~1억 250만원',
  dDay: 'D-7',
  deadline: '11월 11일(수)',
  /** 구역 출구 예상 최대 지연: 기준일 → 결정 기한에 확정할 때(결정 기한 카드 '출구 지연 기준일 9일 → … 16일'). */
  exit: { asOf: 9, atDeadline: 16 },
  /** 결정 기한 다음 날부터 늘어나는 금액(결정 기한 카드 '하루 늦으면' · 곡선 표 · 결재함 '미루면'). */
  later: { on: '11월 12일(목)', amount: '1,867만원' },
  /** 추가손실 곡선의 기간(곡선 탭 머리). */
  horizon: { from: '11월 4일(수)', to: '1월 3일(일)' },
  /** 판단 요약 첫 줄(계약 1.35.0): 추가 공수 · 추가 재료비. */
  labor: { hours: '807 MH', money: '4,007만원', works: '재작업 · 용접 · 가공 · 도면' },
  material: { value: '327만원', parts: '자재 차이 63만원 · 구매 264만원', ordered: 1 },
  /** 블록별 강재 중량 변화 합계. */
  weight: '+0.69t',
} as const
