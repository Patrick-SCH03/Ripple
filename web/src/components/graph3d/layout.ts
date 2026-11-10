// 3D 배치 표(가상 배치, 합성 호선 S-001): 블록 코드 → 선체 안 자리(조각)·라벨 자리. 엔진·지도 데이터에는 좌표가 없어
// 화면 쪽에만 둔다. 블록 코드·이름·이웃은 generator/config.yaml(blocks · adjacency)과 같다(layout.test.ts가 대조).
//
// 공개된 수에즈막스급 대표 주요 치수에 맞춘 가상 배치(실제 도면 아님). 구획 치수는 일반 구조 규칙의 범위 가운데 둥근 값:
// - 이중저 높이 2.5 · 이중선측 폭 2.5(MARPOL 부속서 I 규칙 19의 최소 2.0m 이상, 흔한 2~3m의 가운데) · 호퍼(이중선측 아래 경사)
//   높이·폭 5 · 중심선 종격벽 두께 0.9 · 횡격벽 블록 길이 1.5 · 갑판 블록 깊이 1.5.
// - 길이 방향: 선미 블록 x −5~12 · 기관실 12~42(30m) · 펌프룸 42~48 · 화물탱크 6쌍 48~240(한 탱크 32m, No.6이 맨 뒤) ·
//   코퍼댐 240~244 · 선수 평형수탱크 244~256(충돌격벽 = FP 뒤 20m, 수선간장의 7.6%) · 구상선수 256~.
// - 화물탱크 중 No.3(x 144~176)만 모델 블록이고 나머지는 맥락용 선체다.
import type { Piece } from './hull'
import { SHIP } from './hull'

export const SHIP_ID = 'S-001'

export type ZoneCode = 'ZCT' | 'ZER' | 'ZFO'

export interface BlockPlace {
  code: string
  zone: ZoneCode
  name: string
  pieces: Piece[]
  /** 라벨 자리(블록 위·바깥쪽 — 화면에서 겹치면 ShipLabels가 비켜 놓는다). */
  label: readonly [number, number, number]
}

export const DB = 2.5
export const SIDE = 2.5
export const HOPPER = { y0: DB, h: 5, w: 5 } as const
const DECK = SHIP.depth - 1.5
const TANK = 32
const BULKHEAD = 1.5
const LBHD = 0.45
export const CARGO_AFT = 48
export const CARGO_FWD = CARGO_AFT + 6 * TANK
const ER_AFT = 12
const ER_FWD = 42
const ER_DB = 3
const ER_SIDE = 3
const FLAT: readonly [number, number] = [11.6, 12.4]
const COLLISION = 244
const BULB_AFT = 256
const BULB_TOP = 12

/** No.n 화물탱크의 뒤 끝 x(No.6이 맨 뒤). */
export const tankAft = (no: number) => CARGO_AFT + (6 - no) * TANK

/** 화물탱크 하나를 블록 조각으로 나눈 것(좌·우 이중저, 좌·우 선측(호퍼 포함), 종격벽, 횡격벽, 갑판). */
function tankPieces(no: number): Record<'bp' | 'bs' | 'sp' | 'ss' | 'l' | 't' | 'd', Piece> {
  const x0 = tankAft(no)
  const x1 = x0 + TANK
  const lx0 = x0 + BULKHEAD
  // No.1 앞 끝에는 화물구역 앞 횡격벽이 있어 종격벽이 그 앞에서 멈춘다
  const lx1 = no === 1 ? x1 - BULKHEAD : x1
  return {
    bp: { x: [x0, x1], y: [0, DB], z: [-30, 0] },
    bs: { x: [x0, x1], y: [0, DB], z: [0, 30] },
    sp: { x: [x0, x1], y: [DB, DECK], mode: 'port', t: SIDE, hopper: HOPPER },
    ss: { x: [x0, x1], y: [DB, DECK], mode: 'stbd', t: SIDE, hopper: HOPPER },
    l: { x: [lx0, lx1], y: [DB, DECK], z: [-LBHD, LBHD] },
    t: { x: [x0, lx0], y: [DB, DECK], mode: 'inner', t: SIDE, hopper: HOPPER },
    d: { x: [x0, x1], y: [DECK, SHIP.depth] },
  }
}

const no3 = tankPieces(3)
const X3 = tankAft(3)
const L3 = X3 + BULKHEAD

export const BLOCK_LAYOUT: readonly BlockPlace[] = [
  // 화물탱크 구역 No.3 COT — 좌현 라벨은 뒤쪽, 우현은 앞쪽으로 비켜 둔다
  { code: 'B31P', zone: 'ZCT', name: 'No.3 COT 이중저 좌', pieces: [no3.bp], label: [X3 + 9, 1.2, -27] },
  { code: 'B31S', zone: 'ZCT', name: 'No.3 COT 이중저 우', pieces: [no3.bs], label: [X3 + 23, 1.2, 27] },
  { code: 'S31P', zone: 'ZCT', name: 'No.3 COT 선측 좌', pieces: [no3.sp], label: [X3 + 9, 13, -27] },
  { code: 'S31S', zone: 'ZCT', name: 'No.3 COT 선측 우', pieces: [no3.ss], label: [X3 + 23, 13, 27] },
  { code: 'L31C', zone: 'ZCT', name: '중심선 종격벽', pieces: [no3.l], label: [X3 + 24, 14, 0] },
  { code: 'T31C', zone: 'ZCT', name: 'No.3 COT 횡격벽', pieces: [no3.t], label: [X3 + 0.75, 8, -11] },
  { code: 'D31C', zone: 'ZCT', name: 'No.3 COT 갑판', pieces: [no3.d], label: [X3 + 14, 25.5, 0] },
  // 기관실·펌프룸 구역
  {
    code: 'A11C',
    zone: 'ZER',
    name: '선미(프로펠러 보스·러더)',
    pieces: [
      { x: [SHIP.aftEnd, ER_AFT], y: [0, SHIP.transomLow] },
      // 러더(반평형 날개, 코드 6.4 · 높이 12)와 프로펠러 축 보스(선미재 → 프로펠러 허브)
      { x: [-4.2, 2.2], y: [1, 13], z: [-0.65, 0.65], box: true, shape: 'rudder' },
      { x: [5.9, SHIP.sternPost], y: [3.6, 6.4], z: [-1.4, 1.4], box: true, shape: 'boss' },
    ],
    label: [-9, 12, 0],
  },
  { code: 'E11C', zone: 'ZER', name: '기관실 이중저', pieces: [{ x: [ER_AFT, ER_FWD], y: [0, ER_DB] }], label: [27, 1.5, 22] },
  {
    code: 'E21C',
    zone: 'ZER',
    name: '기관실 측부·플랫',
    pieces: [
      { x: [ER_AFT, ER_FWD], y: [ER_DB, DECK], mode: 'port', t: ER_SIDE },
      { x: [ER_AFT, ER_FWD], y: [ER_DB, DECK], mode: 'stbd', t: ER_SIDE },
      { x: [35, ER_FWD], y: FLAT, mode: 'inner', t: ER_SIDE },
    ],
    label: [33, 15, 26],
  },
  { code: 'P11C', zone: 'ZER', name: '펌프룸', pieces: [{ x: [ER_FWD, CARGO_AFT], y: [0, SHIP.depth] }], label: [45, 26, 0] },
  // 선수부
  { code: 'F11C', zone: 'ZFO', name: '구상선수', pieces: [{ x: [BULB_AFT, SHIP.fwdEnd], y: [0, BULB_TOP] }], label: [274, 6, 0] },
  { code: 'F21C', zone: 'ZFO', name: '선수 평형수탱크', pieces: [{ x: [COLLISION, BULB_AFT], y: [0, SHIP.depth] }], label: [250, 12, 25] },
  {
    code: 'F31C',
    zone: 'ZFO',
    name: '선수루 갑판',
    pieces: [{ x: [SHIP.forecastleAft, SHIP.fwdEnd], y: [SHIP.depth, SHIP.forecastle + 1] }],
    label: [254, 29, 0],
  },
]

/** 블록 이음(맞대기 용접 블록 쌍) — generator/config.yaml adjacency와 같다. */
export const ADJACENCY: readonly (readonly [string, string])[] = [
  ['B31P', 'B31S'],
  ['B31P', 'S31P'],
  ['B31S', 'S31S'],
  ['S31P', 'D31C'],
  ['S31S', 'D31C'],
  ['L31C', 'B31P'],
  ['L31C', 'D31C'],
  ['T31C', 'B31P'],
  ['T31C', 'L31C'],
  ['E11C', 'E21C'],
  ['E21C', 'P11C'],
  ['P11C', 'T31C'],
  ['A11C', 'E11C'],
  ['F11C', 'F21C'],
  ['F21C', 'F31C'],
]

/** 이음면: 두 블록이 맞닿는 면을 얇은 판(두께 2 × JOINT)으로. axis = 면의 법선 축. */
export interface Joint {
  pair: readonly [string, string]
  axis: 'x' | 'y' | 'z'
  pieces: Piece[]
}

export const JOINT = 0.15
const J = JOINT
const at = (v: number): readonly [number, number] => [v - J, v + J]
const sideT = SIDE + HOPPER.w

/** 맞닿은 이웃 블록 쌍의 이음면(맞닿지 않는 쌍 — 펌프룸·No.3 횡격벽처럼 떨어진 쌍 — 은 없다, 화면은 낮은 호로 잇는다). */
export const JOINTS: readonly Joint[] = [
  { pair: ['B31P', 'B31S'], axis: 'z', pieces: [{ x: [X3, X3 + TANK], y: [0, DB], z: at(0) }] },
  { pair: ['B31P', 'S31P'], axis: 'y', pieces: [{ x: [X3, X3 + TANK], y: at(DB), mode: 'port', t: sideT }] },
  { pair: ['B31S', 'S31S'], axis: 'y', pieces: [{ x: [X3, X3 + TANK], y: at(DB), mode: 'stbd', t: sideT }] },
  { pair: ['S31P', 'D31C'], axis: 'y', pieces: [{ x: [X3, X3 + TANK], y: at(DECK), mode: 'port', t: SIDE }] },
  { pair: ['S31S', 'D31C'], axis: 'y', pieces: [{ x: [X3, X3 + TANK], y: at(DECK), mode: 'stbd', t: SIDE }] },
  { pair: ['L31C', 'B31P'], axis: 'y', pieces: [{ x: [L3, X3 + TANK], y: at(DB), z: [-LBHD, 0] }] },
  { pair: ['L31C', 'D31C'], axis: 'y', pieces: [{ x: [L3, X3 + TANK], y: at(DECK), z: [-LBHD, LBHD] }] },
  { pair: ['T31C', 'B31P'], axis: 'y', pieces: [{ x: [X3, L3], y: at(DB), z: [-30, 0], mode: 'inner', t: sideT }] },
  { pair: ['T31C', 'L31C'], axis: 'x', pieces: [{ x: at(L3), y: [DB, DECK], z: [-LBHD, LBHD] }] },
  {
    pair: ['E11C', 'E21C'],
    axis: 'y',
    pieces: [
      { x: [ER_AFT, ER_FWD], y: at(ER_DB), mode: 'port', t: ER_SIDE },
      { x: [ER_AFT, ER_FWD], y: at(ER_DB), mode: 'stbd', t: ER_SIDE },
    ],
  },
  {
    pair: ['E21C', 'P11C'],
    axis: 'x',
    pieces: [
      { x: at(ER_FWD), y: [ER_DB, DECK], mode: 'port', t: ER_SIDE },
      { x: at(ER_FWD), y: [ER_DB, DECK], mode: 'stbd', t: ER_SIDE },
      { x: at(ER_FWD), y: FLAT, mode: 'inner', t: ER_SIDE },
    ],
  },
  { pair: ['A11C', 'E11C'], axis: 'x', pieces: [{ x: at(ER_AFT), y: [0, ER_DB] }] },
  { pair: ['F11C', 'F21C'], axis: 'x', pieces: [{ x: at(BULB_AFT), y: [0, BULB_TOP] }] },
  { pair: ['F21C', 'F31C'], axis: 'y', pieces: [{ x: [COLLISION, BULB_AFT], y: at(SHIP.depth) }] },
]

/** 두 블록의 이음면(순서 무관). 맞닿지 않는 쌍이면 undefined. */
export function jointOf(a: string, b: string): Joint | undefined {
  return JOINTS.find(({ pair }) => (pair[0] === a && pair[1] === b) || (pair[0] === b && pair[1] === a))
}

/** 맥락용 선체 구조(클릭 대상 아님, 경계선만): 다른 화물탱크 · 코퍼댐 · 기관실 위 · 조타기실 · 체인 로커 · 주기관. */
export function contextPieces(): Piece[] {
  const tanks = [6, 5, 4, 2, 1].flatMap((no) => Object.values(tankPieces(no)))
  const fwdBulkhead: Piece = { x: [CARGO_FWD - BULKHEAD, CARGO_FWD], y: [DB, DECK], mode: 'inner', t: SIDE, hopper: HOPPER }
  return [
    ...tanks,
    fwdBulkhead,
    { x: [CARGO_FWD, COLLISION], y: [0, SHIP.depth] }, // 코퍼댐
    { x: [ER_AFT, ER_FWD], y: [DECK, SHIP.depth] }, // 기관실 위 갑판
    { x: [SHIP.aftEnd, ER_AFT], y: [SHIP.transomLow, SHIP.depth] }, // 조타기실·선미 갑판
    { x: [BULB_AFT, SHIP.fwdEnd], y: [BULB_TOP, SHIP.depth] }, // 체인 로커·창고
    { x: [22, 34], y: [4, 14], z: [-3.2, 3.2], box: true }, // 주기관
  ]
}

/** 상부 구조(반투명 맥락): 거주구 3단 · 조타실 · 선교 윙 · 연돌. */
export function superstructurePieces(): Piece[] {
  const d = SHIP.depth
  return [
    { x: [14.5, 30.5], y: [d, d + 11.2], z: [-14, 14], box: true },
    { x: [18.5, 30.5], y: [d + 11.2, d + 14], z: [-12, 12], box: true },
    { x: [24.5, 30.5], y: [d + 14, d + 17], z: [-13, 13], box: true },
    { x: [25.5, 29.5], y: [d + 14, d + 15], z: [13, 23.5], box: true },
    { x: [25.5, 29.5], y: [d + 14, d + 15], z: [-23.5, -13], box: true },
    { x: [7.5, 14], y: [d, d + 23], z: [-4.2, 4.2], box: true },
  ]
}

/** 횡격벽·구획 경계 x(늑골선을 그릴 자리). */
export const FRAME_STATIONS: readonly number[] = [
  ER_AFT,
  ER_FWD,
  ...[6, 5, 4, 3, 2, 1].map(tankAft),
  CARGO_FWD,
  COLLISION,
  BULB_AFT,
]

/** 맥락 이름표(작게): 화물탱크 번호와 선수·선미. */
export const CONTEXT_LABELS: readonly { text: string; at: readonly [number, number, number] }[] = [
  ...[6, 5, 4, 2, 1].map((no) => ({ text: `No.${no} COT`, at: [tankAft(no) + TANK / 2, SHIP.depth + 1.5, 0] as const })),
  { text: '선수', at: [SHIP.fwdEnd + 6, 27, 0] },
  { text: '선미', at: [SHIP.aftEnd - 7, 25, 0] },
]

/** 화면 라벨 자리 전부(블록 코드, 맥락 이름표는 'ctx:' + 글). */
export const LABEL_ANCHORS: readonly { key: string; at: readonly [number, number, number] }[] = [
  ...BLOCK_LAYOUT.map((place) => ({ key: place.code, at: place.label })),
  ...CONTEXT_LABELS.map((label) => ({ key: `ctx:${label.text}`, at: label.at })),
]

export type ViewName = 'whole' | 'cargo' | 'stern' | 'bow'

export interface ShipView {
  name: ViewName
  label: string
  /** 맞출 상자(최소·최대). */
  box: readonly [readonly [number, number, number], readonly [number, number, number]]
  /** 카메라 방향(camera-controls 구면 좌표: 방위 θ — 0이면 우현에서, +면 선수 쪽 / 극각 φ — 0이면 바로 위). */
  azimuth: number
  polar: number
}

export const VIEWS: readonly ShipView[] = [
  { name: 'whole', label: '전체', box: [[SHIP.aftEnd, 0, -24], [SHIP.fwdEnd, 46, 24]], azimuth: 0.5, polar: 1.02 },
  { name: 'cargo', label: '화물창', box: [[X3 - 2, 0, -24], [X3 + TANK + 2, 26, 24]], azimuth: 0.78, polar: 1.02 },
  { name: 'stern', label: '선미', box: [[SHIP.aftEnd - 2, 0, -24], [CARGO_AFT + 2, 46, 24]], azimuth: -0.55, polar: 1.15 },
  { name: 'bow', label: '선수', box: [[232, 0, -24], [SHIP.fwdEnd + 2, 29, 24]], azimuth: 0.55, polar: 1.2 },
]

export const ZONE_VIEW: Record<ZoneCode, ViewName> = { ZCT: 'cargo', ZER: 'stern', ZFO: 'bow' }
