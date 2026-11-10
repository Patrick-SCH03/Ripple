// 시연 시나리오(위 막대 '시연' 단추, components/demo): 업무 화면이 스스로 움직이는 선언형 단계 목록.
// 셀렉터는 화면의 testid·aria-label·단추 이름에 기대므로 그 이름을 바꾸면 여기와
// lib/demo.test.ts를 함께 본다(검사가 그 이름들이 화면 소스에 실제로 있는지 본다). 실행기는 단계마다 요소가 나타날 때까지
// 기다리고, 스크롤·강조한 뒤 실제 단추를 누른다.
// 데이터를 바꾸는 동작(기록·검토 요청·결재·통보·지도 바꾸기·상태 올리기)은 넣지 않는다: 분석·가정 계산·탭 이동·되돌리기만이라
// 몇 번 돌려도 같은 결과다(lib/demo.ts unsafeReason이 실행 전에 한 번 더 막는다).
import { ASSISTANT_INPUT_ID, ASSISTANT_TOGGLE_ID } from './domIds'

export type DemoAction = 'scroll' | 'click' | 'tab' | 'type' | 'wait'

/** 화면에서 찾을 요소: CSS 셀렉터 + (같은 셀렉터가 여럿이면) 글에 들어 있어야 할 말. */
export interface DemoTarget {
  target: string
  text?: string
  /** 글이 정확히 같아야 한다(부분 일치가 아니라 — '새 대화'가 '새 대화로 시작'에 걸리지 않게). */
  exact?: boolean
}

/** 동작 뒤 기다릴 결과. */
export interface DemoWait extends DemoTarget {
  /** 사라질 때까지 기다린다(되돌리기 뒤 바뀐 점 띠처럼). */
  gone?: boolean
  /** 동작 전에 없던 요소가 새로 나타날 때까지(같은 모양이 이미 있는 비서 답). */
  fresh?: boolean
  /** 나타나면 강조를 그 요소로 옮긴다(누른 단추가 사라지거나 결과가 다른 곳에 생길 때). */
  spot?: boolean
  /** 제한 시간(ms). 분석을 기다리면 길게. */
  timeout?: number
  /**
   * 이 셀렉터(오류 알림·되묻는 비서 답)가 동작 뒤 새로 보이면 제한 시간을 기다리지 않고 바로 멈춘다 — 발표장에서 30초 멈춘
   * 화면이 없게. 동작 전부터 있던 것은 세지 않는다.
   */
  failIf?: string
}

export interface DemoStep extends DemoTarget {
  action: DemoAction
  /** 안내 띠 문구(명사형). 준비(quiet) 단계는 띠에 내지 않는다. */
  caption: string
  /** 스크롤·강조할 요소(없으면 target). 예: '맞춤 보기'를 누르지만 강조는 영향 지도 전체. */
  focus?: string
  /** 스크롤 위치(기본 center). 화면보다 큰 영향 지도는 start. */
  block?: 'start' | 'center'
  /** type: 한 글자씩 넣을 글. */
  value?: string
  waitFor?: DemoWait
  /** 결과를 보여 주는 시간(ms, 기본 DEFAULT_HOLD). */
  hold?: number
  /** 준비 단계: 번호를 매기지 않고 강조·머무름 없이 지나간다. */
  quiet?: boolean
  /** 대상이 없으면 문구도 내지 않고 건너뛴다(마감일 단추가 없는 날·알림 초안이 없는 결과). */
  optional?: boolean
  /** 이 요소가 이미 있으면 건너뛴다(비서 칸이 이미 열려 있음). */
  skipIf?: DemoTarget
}

export interface DemoScenario {
  id: string
  name: string
  /** 메뉴의 한 줄 설명. */
  summary: string
  /** 지금 지도 목록에 있어야 하는 설계변경(합성 기본 지도의 샘플). 없으면 메뉴에서 흐리게. */
  needs: readonly string[]
  steps: readonly DemoStep[]
}

const PIPE = 'ECN-D-0043' // 평형수 배관 경로 변경: 결정 기한 · 후행 설치 선택지가 있는 건
const PLATE = 'ECN-D-0119' // B31P 판 두께: 같은 목적의 더 저렴한 대안이 있는 건
const SENTENCE = 'B31P 판 2, 5, 7번 두께 17에서 20으로 변경 (강도 보강)'

const INPUT = `#${ASSISTANT_INPUT_ID}`
const TOGGLE = `#${ASSISTANT_TOGGLE_ID}`
/** 상세가 계산을 마친 상태: 맨 위 결과 알림(ResultNotice)의 상태 줄 — 다시 계산 중·거절·초안 고침 — 이 비어 있다. */
const SETTLED = 'main:not(:has(> [role="status"] > *))'

export const DEMO_SELECTORS = {
  row: 'nav button[data-ecn-item]',
  listOpen: 'button[aria-label="목록 펼치기"]',
  filter: '[aria-label="판정으로 거르기"] button[aria-pressed="false"]',
  /** 상세 머리의 설계변경 번호 — 계산을 마쳤을 때만 찾는다(같은 건을 다시 열어도 재분석을 기다리게). */
  shownEcn: `${SETTLED} [data-testid="detail-ecn"]`,
  top: 'main [data-detail-scroll] > :first-child',
  reasons: '[aria-label="판정 이유"]',
  keyNumbers: '[aria-label="핵심 수치"]',
  deadline: '[data-testid="deadline-apply"]',
  deadlineGuide: '[data-testid="deadline-guide"]',
  map: '[data-testid="impact-map"]',
  mapButton: '[data-testid="impact-map"] button',
  todo: '[data-testid="todo-actions"]',
  todoButton: '[data-testid="todo-actions"] button',
  changes: '[aria-label="바뀐 점"]',
  changesButton: '[aria-label="바뀐 점"] button',
  tab: 'main [role="tab"]',
  advice: '[aria-label="권고"]',
  adviceButton: '[aria-label="권고"] button',
  options: 'ul[aria-label="대안"]',
  optionRow: 'ul[aria-label="대안"] button[aria-expanded="false"]',
  optionDetail: 'ul[aria-label="대안"] li > [id^="alternative-"]',
  costLines: 'ul[aria-label="비용 줄"]',
  toggle: TOGGLE,
  /** 비서가 열려 있음: 넓은 화면은 칸 켜짐(aria-pressed), 1024~1439px는 시트 열림(aria-expanded). */
  toggleOpen: `${TOGGLE}[aria-pressed="true"], ${TOGGLE}[aria-expanded="true"]`,
  input: INPUT,
  /** 비서 칸(넓은 화면) · 비서 시트(1024~1439px) 머리의 단추. */
  newChat: 'aside button, [role="dialog"] button',
  send: `form:has(${INPUT}) button[type="submit"]`,
  /** 분석한 비서 답이 상세에 열림(TurnView data-turn-state·data-shown). */
  analyzedReply: 'article[data-turn-state="analyzed"][data-shown="true"]',
  /** 분석 대신 되묻는 비서 답. */
  questionReply: 'article[data-turn-state="asking"]',
  lastAnalyzed: 'article[data-turn-state="analyzed"]:last-of-type',
  drafts: 'section[aria-label="알림 초안"]',
  /** 분석 실패(상세 맨 위 ResultNotice) · 탭 안 계산 실패(대안) · 비서 요청 실패. */
  analysisError: 'main > [role="alert"]',
  tabError: 'main [role="tabpanel"] > [role="alert"]',
  assistantError: 'aside [role="alert"], [role="dialog"] [role="alert"]',
} as const

const S = DEMO_SELECTORS
const ANALYSIS_MS = 30000
/** 다시 분석을 기다리는 결과: 분석이 실패해 오류 알림이 뜨면 바로 멈춘다. */
const analysed = (want: DemoWait): DemoWait => ({ timeout: ANALYSIS_MS, failIf: S.analysisError, ...want })

/** 고를 설계변경이 목록에 보이게: 접힌 목록을 펴고 판정 거르기를 '전체'로(이미 그렇다면 건너뜀). */
function showList(): DemoStep[] {
  return [
    { action: 'click', target: S.listOpen, caption: '목록 펼치기', quiet: true, optional: true },
    { action: 'click', target: S.filter, text: '전체', caption: '판정 거르기를 전체로', quiet: true, optional: true },
  ]
}

/** 목록에서 설계변경을 연다 — 상세 머리에 그 번호가 나오고 계산을 마치면(다시 계산 중 줄이 사라지면) 다음으로. */
function openEcn(ecnId: string, caption: string, extra: Partial<DemoStep> = {}): DemoStep {
  return {
    action: 'click',
    target: S.row,
    text: ecnId,
    caption,
    waitFor: analysed({ target: S.shownEcn, text: ecnId }),
    hold: 1600,
    ...extra,
  }
}

/** 처음 화면으로: 목록에서 그 설계변경을 다시 열어(가정 계산·확정일을 처음대로) 상세를 맨 위로 올린다. */
function restore(ecnId: string, caption: string): DemoStep[] {
  return [
    openEcn(ecnId, caption, { hold: 2200 }),
    { action: 'scroll', target: S.top, caption: '상세 맨 위로', quiet: true },
  ]
}

/** 영향 지도를 화면 위에 맞추고 '맞춤 보기'로 전체를 맞춘다(강조는 지도 전체). */
function fitMap(caption: string, hold = 2600): DemoStep {
  return { action: 'click', target: S.mapButton, text: '맞춤 보기', focus: S.map, block: 'start', caption, hold }
}

const IMPACT_TO_TODO: DemoScenario = {
  id: 'impact-to-todo',
  name: '할 일로 바뀌는 영향 지도',
  summary: '배관 경로 변경 — 결정 기한으로 다시 계산하고, 후행 설치로 바꿔 지도가 달라지는 모습',
  needs: [PIPE],
  steps: [
    ...showList(),
    openEcn(PIPE, '평형수 배관 경로 변경 열기'),
    { action: 'scroll', target: S.reasons, caption: '판정과 이유 먼저 — 판단 근거 한 줄씩', hold: 2800 },
    { action: 'scroll', target: S.keyNumbers, caption: '드는 비용 · 추가손실 없이 정할 수 있는 기한', hold: 2800 },
    {
      // 마감일이 오늘이거나 기간 안 없음인 날에는 단추가 없다 — 그날은 이 단계만 건너뛴다
      action: 'click',
      target: S.deadline,
      optional: true,
      caption: '결정 기한 단추 — 그날 확정으로 다시 계산',
      waitFor: analysed({ target: S.deadlineGuide, text: '결정 기한', spot: true }),
      hold: 2600,
    },
    fitMap('영향 지도 — 바뀐 배관에서 발주 · 블록 · 도면 · 공정으로 이어지는 영향', 3000),
    { action: 'scroll', target: S.todo, caption: '할 일 — 지금 할 수 있는 조치 한 줄씩', hold: 2400 },
    {
      action: 'click',
      target: S.todoButton,
      text: '후행 설치로 계산',
      caption: '늦게 오는 배관 대기 대신 탑재 뒤 선상 설치 — 가정 계산',
      waitFor: analysed({ target: S.changes, spot: true }),
      hold: 3000,
    },
    { action: 'scroll', target: S.keyNumbers, caption: '핵심 수치도 후행 설치 기준으로 다시 계산', hold: 2400 },
    // 후행 설치로도 탑재 지연이 0일이 되지는 않는다(판정 이유가 그대로일 수 있음) — 지연이 '빠졌다'고 하지 않는다
    fitMap('영향 지도도 후행 설치 기준 — 탑재 대기 지연 감소', 3000),
    {
      action: 'click',
      target: S.changesButton,
      text: '되돌리기',
      caption: '되돌리기 — 다시 계산 없이 바로 전 결과로',
      waitFor: { target: S.changes, gone: true },
      hold: 1800,
    },
    ...restore(PIPE, '처음 화면으로 — 가정 계산이라 기록 없음'),
  ],
}

const SPOKEN_CHANGE: DemoScenario = {
  id: 'spoken-change',
  name: '말로 넣어 분석하기',
  summary: 'AI 비서에 현장 표현 그대로 적으면 지도와 대조해 바로 분석하는 모습',
  needs: [PLATE],
  steps: [
    ...showList(),
    // 비서는 고른 설계변경의 호선·기준일·확정일을 이어받는다 — 앞 시나리오의 확정일이 따라가지 않게 다른 건을 새로 연다
    openEcn(PLATE, '같은 호선 설계변경 열어 두기', { quiet: true }),
    {
      action: 'click',
      target: S.toggle,
      caption: 'AI 비서 열기',
      skipIf: { target: S.input },
      waitFor: { target: S.input },
      hold: 2200,
    },
    { action: 'click', target: S.newChat, text: '새 대화', exact: true, caption: '새 대화로', quiet: true, optional: true },
    { action: 'type', target: S.input, value: SENTENCE, caption: '새 설계변경을 현장 표현 그대로 입력', hold: 1600 },
    {
      // 비서가 분석 대신 되물으면(대상이 모호함 등) 아래 문구가 옛 결과를 가리키게 되므로 바로 멈춘다
      action: 'click',
      target: S.send,
      caption: '보내면 연결 지도와 대조해 바로 분석 — 숫자는 AI가 아닌 규칙 계산',
      waitFor: {
        target: S.analyzedReply,
        fresh: true,
        spot: true,
        timeout: ANALYSIS_MS,
        failIf: `${S.assistantError}, ${S.questionReply}`,
      },
      hold: 3000,
    },
    {
      // 알림 초안이 없는 결과면 문구 없이 건너뛴다
      action: 'wait',
      target: `${S.lastAnalyzed} ${S.drafts}`,
      optional: true,
      caption: '협력사·담당 부서에 보낼 알림 초안까지',
      hold: 2800,
    },
    {
      action: 'click',
      target: S.toggleOpen,
      caption: 'AI 비서 닫고 상세에서 결과 크게 보기',
      optional: true,
      waitFor: { target: S.input, gone: true },
      hold: 1800,
    },
    { action: 'scroll', target: S.reasons, caption: '말로 넣은 변경도 같은 규칙으로 판정 · 이유', hold: 2600 },
    { action: 'scroll', target: S.keyNumbers, caption: '총변경비용 · 결정 기한도 같은 계산', hold: 2800 },
    fitMap('영향 지도 — 바꾼 판에서 블록 · 발주 · 공정으로 이어지는 영향', 3000),
    { action: 'scroll', target: S.todo, optional: true, caption: '이 변경에서 지금 할 조치도 바로', hold: 2400 },
    ...restore(PLATE, '처음 화면으로 — 분석만, 기록 없음'),
  ],
}

const CHEAPER_OPTION: DemoScenario = {
  id: 'cheaper-option',
  name: '더 저렴한 대안 찾기',
  summary: '판 두께 변경 — 같은 목적을 더 싸게 이루는 대안을 비교하고 그 대안으로 다시 분석',
  needs: [PLATE],
  steps: [
    ...showList(),
    openEcn(PLATE, '판 두께 변경 열기'),
    { action: 'scroll', target: S.keyNumbers, caption: '요청 그대로 할 때 비용 · 결정 기한', hold: 2600 },
    { action: 'tab', target: S.tab, text: '비용', caption: '비용 탭으로', quiet: true },
    { action: 'scroll', target: S.costLines, caption: '비용 탭 — 항목별 금액, 큰 순 · 근거 포함', hold: 2800 },
    {
      action: 'tab',
      target: S.tab,
      text: '대안',
      caption: '대안 탭 — 같은 목적의 다른 방법을 함께 계산해 비교',
      waitFor: { target: S.advice, spot: true, timeout: ANALYSIS_MS, failIf: S.tabError },
      hold: 3000,
    },
    { action: 'scroll', target: S.options, caption: '대안 표 — 판정 · 출구 지연 · 결정 기한 · 총변경비용 나란히', hold: 2800 },
    {
      action: 'click',
      target: S.optionRow,
      text: '권고',
      caption: '권고 대안 펼침 — 강도 판정 근거 · 바꾸는 것',
      waitFor: { target: S.optionDetail, spot: true },
      hold: 3000,
    },
    {
      action: 'click',
      target: S.adviceButton,
      text: '이 대안으로 분석 보기',
      caption: '최저가 조합 선택 · 그 대안으로 다시 분석',
      waitFor: analysed({ target: S.changes, spot: true }),
      hold: 3000,
    },
    { action: 'scroll', target: S.keyNumbers, caption: '대안의 판정 · 비용 · 결정 기한 — 바뀐 점 띠에서 전·후 비교', hold: 2600 },
    fitMap('대안의 영향 지도 — 빠지는 것 · 생기는 것', 3000),
    {
      action: 'click',
      target: S.changesButton,
      text: '되돌리기',
      caption: '되돌리기 — 요청한 원래 결과로',
      waitFor: { target: S.changes, gone: true },
      hold: 1800,
    },
    ...restore(PLATE, '처음 화면으로 — 비교만, 기록 없음'),
  ],
}

export const DEMO_SCENARIOS: readonly DemoScenario[] = [IMPACT_TO_TODO, SPOKEN_CHANGE, CHEAPER_OPTION]