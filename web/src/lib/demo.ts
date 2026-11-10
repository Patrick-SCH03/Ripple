// 시연 실행의 순수 부분(components/demo가 쓴다): 단계 번호 · 띠 이름·문구 · 단계마다 기다림·스크롤·문구 시점 판단 ·
// 머무는 시간 어림 · 지도에서 돌릴 수 있는지 · 데이터를 바꾸는 단계인지. 화면(DOM)은 만지지 않는다 — vitest로 성질을
// 검사한다(demo.test.ts).
import { DEMO_SELECTORS as S, type DemoScenario, type DemoStep, type DemoTarget } from './demoScenarios'

/** 실행 상태: 쉬는 중 · 도는 중 · 막힘(띠를 잠깐 남김) · 마침(띠를 잠깐 남김). */
export type DemoPhase = 'idle' | 'running' | 'stuck' | 'done'

/** 결과를 보여 주는 기본 시간(ms). 단계마다 1.5~3초. */
export const DEFAULT_HOLD = 2200
/** 강조한 뒤 누르기 전까지(띠 문구를 읽을 틈). */
export const LEAD_MS = 1200
/** 스크롤이 멈추기를 기다리는 최대 시간. */
export const SETTLE_MS = 900
/** 한 글자 넣는 간격. */
export const TYPE_MS = 65
/** 요소가 나타나기를 기다리는 기본 제한 시간(분석을 기다리는 단계는 waitFor.timeout). */
export const FIND_TIMEOUT = 12000
/** 준비 단계가 대상을 찾아보는 시간 — 접힌 목록 펼치기처럼 있으면 이미 있으므로 짧게 보고 건너뛴다. */
export const OPTIONAL_WAIT = 120
/**
 * 번호가 붙는 optional 단계가 대상을 찾아보는 시간. 앞 단계가 계산을 마칠 때까지 기다렸으므로 대상은 있으면 이미 있다 —
 * 없을 때 말없이 머무는 틈을 짧게.
 */
export const OPTIONAL_STEP_WAIT = 500
/** 누른 뒤 결과를 보기 전 기다림 — 화면이 누름을 반영해(다시 계산 중 줄 등) 그리기 전의 옛 화면을 결과로 착각하지 않게. */
export const RENDER_MS = 150
/** 끝났을 때·멈췄을 때 띠를 남겨 두는 시간. */
export const DONE_MS = 2600
export const STUCK_MS = 7000

export const STUCK_TEXT = '여기서 멈춤 — 화면 확인 필요'
export const DONE_TEXT = '시연 끝 — 처음 화면으로 돌아옴'

/** 띠 앞머리: '시연 · 2/7'. */
export function bandLabel(n: number, total: number): string {
  return `시연 · ${n}/${total}`
}

/** 띠 본문: 도는 중이면 지금 단계 문구, 막히면 STUCK_TEXT, 마치면 DONE_TEXT. */
export function bandText(phase: Exclude<DemoPhase, 'idle'>, caption: string): string {
  if (phase === 'stuck') return STUCK_TEXT
  return phase === 'running' ? caption : DONE_TEXT
}

/** 띠에 번호를 다는 단계 수(준비 단계는 세지 않는다). */
export function countedSteps(steps: readonly DemoStep[]): number {
  return steps.filter((step) => !step.quiet).length
}

/**
 * 지금 보일 단계 번호와 전체 수: 이미 보여 준 단계(shown) 다음 번호이고, 대상이 없어 건너뛴 단계(skipped)는 전체에서 뺀다 —
 * 마감일 단추가 없는 날에도 '3/11 → 5/11'처럼 번호가 튀지 않고, 마지막 단계에서 n = 전체가 된다.
 */
export function progressFrom(counted: number, shown: number, skipped: number): { n: number; total: number } {
  const total = Math.max(1, counted - skipped)
  return { n: Math.min(total, shown + 1), total }
}

/** 한 시나리오를 도는 동안의 번호 세기: show는 띠에 낼 번호를 주며 세고, skip은 건너뛴 단계를 센다(준비 단계는 빼고). */
export function progressCounter(steps: readonly DemoStep[]) {
  const counted = countedSteps(steps)
  let shown = 0
  let skipped = 0
  return {
    show(): { n: number; total: number } {
      const at = progressFrom(counted, shown, skipped)
      shown += 1
      return at
    },
    skip(step: DemoStep): void {
      if (!step.quiet) skipped += 1
    },
  }
}

/** 요소에 손을 대는 단계(누르기·탭 바꾸기·글 넣기): 대상이 쓸 수 있는 상태(막히지 않음)여야 하고, 누르기 전에 읽을 틈을 준다. */
export function touches(step: DemoStep): boolean {
  return step.action === 'click' || step.action === 'tab' || step.action === 'type'
}

/** 단추를 누르는 단계(누르기·탭 바꾸기): 허용 목록에 있어야 하고, 누른 순간 강조 테두리를 깜빡인다. */
export function presses(step: DemoStep): boolean {
  return step.action === 'click' || step.action === 'tab'
}

/** 대상을 찾아보는 시간: 꼭 하는 단계는 FIND_TIMEOUT, optional 단계는 짧게(준비 단계는 더 짧게). */
export function findTimeout(step: DemoStep): number {
  if (!step.optional) return FIND_TIMEOUT
  return step.quiet ? OPTIONAL_WAIT : OPTIONAL_STEP_WAIT
}

/**
 * 띠 문구를 낼 때: 꼭 하는 단계는 대상을 기다리는 동안에도 무엇을 하는지 띄우고(before), optional 단계는 대상이 있을 때만
 * 띄운다(found — 없으면 말없이 건너뜀). 준비 단계는 내지 않는다(never).
 */
export function captionWhen(step: DemoStep): 'before' | 'found' | 'never' {
  if (step.quiet) return 'never'
  return step.optional ? 'found' : 'before'
}

/** 대상을 화면 안으로 옮길 위치: 번호 단계는 강조와 함께(기본 center), 준비 스크롤은 옮기기만(기본 start), 그 밖은 옮기지 않음. */
export function revealBlock(step: DemoStep): 'start' | 'center' | null {
  if (!step.quiet) return step.block ?? 'center'
  return step.action === 'scroll' ? (step.block ?? 'start') : null
}

/** 강조한 뒤 손대기 전까지 읽을 틈(ms): 번호 단계가 요소에 손을 댈 때만. */
export function leadMs(step: DemoStep): number {
  return !step.quiet && touches(step) ? LEAD_MS : 0
}

/** 멈춘 이유에 붙일 대상 이름: 셀렉터와 (있으면) 찾는 글. */
export function targetLabel(want: DemoTarget): string {
  return `${want.target} ${want.text ?? ''}`
}

/** 분석 대기를 뺀 어림 시간(ms): 스크롤 · 읽을 틈 · 타자 · 머무름. */
export function estimateMs(scenario: DemoScenario): number {
  return scenario.steps
    .filter((step) => !step.quiet)
    .reduce((sum, step) => {
      const typing = step.action === 'type' ? (step.value?.length ?? 0) * TYPE_MS : 0
      return sum + SETTLE_MS + leadMs(step) + typing + (step.hold ?? DEFAULT_HOLD)
    }, 0)
}

/** 지금 지도의 설계변경 목록에 시나리오가 쓰는 건이 모두 있나(합성 기본 지도의 샘플). */
export function scenarioReady(scenario: DemoScenario, ecnIds: ReadonlySet<string>): boolean {
  return scenario.needs.every((id) => ecnIds.has(id))
}

/**
 * 시연이 누를 수 있는 단추(가정 계산 · 탭 이동 · 되돌리기 · 비서 대화). 새 단계를 더하면 여기에 먼저 적는다 —
 * 데이터를 바꾸는 단추(검토 요청 · 결재 · 통보 · 지도 바꾸기 · 상태 올리기)는 넣지 않는다.
 */
export const SAFE_CONTROLS: readonly DemoTarget[] = [
  { target: S.row },
  { target: S.listOpen },
  { target: S.filter, text: '전체' },
  { target: S.deadline },
  { target: S.todoButton, text: '후행 설치로 계산' },
  { target: S.todoButton, text: '기다리는 방식으로 계산' },
  { target: S.todoButton, text: '보류 적용' },
  { target: S.changesButton, text: '되돌리기' },
  { target: S.mapButton, text: '맞춤 보기' },
  { target: S.tab },
  { target: S.adviceButton, text: '이 대안으로 분석 보기' },
  { target: S.optionRow, text: '권고' },
  { target: S.toggle },
  { target: S.toggleOpen },
  { target: S.newChat, text: '새 대화', exact: true },
  { target: S.send },
]

/** 데이터를 바꾸는 화면 요소의 이름 조각(testid · 단추 글). 단계의 어느 셀렉터·글에도 들어가면 안 된다. */
const FORBIDDEN_WORDS: readonly string[] = [
  'review',
  'decision',
  'flow-',
  'notice-',
  'approval',
  'status-',
  'intake',
  'fix-',
  'outcome',
  'member',
  'mail',
  'logout',
  'export',
  '검토 요청',
  '승인',
  '반려',
  '보냄',
  '수령 확인',
  '회신',
  '지도로 전환',
  '가져오기',
  '상태 올리기',
  '맞음',
  '고치기',
  '기록 남기기',
]

function wordsOf(step: DemoStep): string[] {
  return [step.target, step.text, step.focus, step.waitFor?.target, step.waitFor?.text, step.skipIf?.target].filter(
    (part): part is string => Boolean(part),
  )
}

/** 허용 목록의 단추인가: 셀렉터가 같고, 목록에 글이 있으면 글도 같고, 글 일치 방식(exact)까지 같아야 한다. */
export function isSafeControl(step: DemoTarget): boolean {
  return SAFE_CONTROLS.some(
    (c) =>
      c.target === step.target && (c.text === undefined || c.text === step.text) && Boolean(c.exact) === Boolean(step.exact),
  )
}

/** 실행하면 안 되는 단계면 그 이유, 아니면 null. 실행기도 단계마다 한 번 더 본다. */
export function unsafeReason(step: DemoStep): string | null {
  const hit = FORBIDDEN_WORDS.find((word) => wordsOf(step).some((part) => part.includes(word)))
  if (hit) return `데이터를 바꾸는 단추 누르기 금지(${hit})`
  if (step.action === 'type' && step.target !== S.input) return '글은 AI 비서 입력 칸에만'
  if (presses(step) && !isSafeControl(step)) return '시연이 누를 수 없는 단추'
  return null
}

/** 시연을 멈추게 하는 키인가: 사람이 누른 키는 모두(Esc는 멈추기 단추와 같음). 조합 키만 누른 것은 빼고. */
export function stopsOnKey(key: string): boolean {
  return !['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(key)
}
