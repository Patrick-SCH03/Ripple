import { describe, expect, it } from 'vitest'
import {
  DEFAULT_HOLD,
  DONE_TEXT,
  FIND_TIMEOUT,
  LEAD_MS,
  OPTIONAL_STEP_WAIT,
  OPTIONAL_WAIT,
  SAFE_CONTROLS,
  STUCK_TEXT,
  bandLabel,
  bandText,
  captionWhen,
  countedSteps,
  estimateMs,
  findTimeout,
  isSafeControl,
  leadMs,
  presses,
  progressCounter,
  progressFrom,
  revealBlock,
  scenarioReady,
  stopsOnKey,
  targetLabel,
  touches,
  unsafeReason,
} from './demo'
import { DEMO_SCENARIOS, DEMO_SELECTORS as S, type DemoAction, type DemoStep } from './demoScenarios'

const steps = DEMO_SCENARIOS.flatMap((scenario) => scenario.steps.map((step) => ({ scenario, step })))

// 화면 소스(시연 코드 자신과 검사 파일은 빼고): 시나리오가 쓰는 이름이 실제 컴포넌트에 있는지 본다
const SOURCES = import.meta.glob<string>(
  ['../**/*.{ts,tsx}', '!../**/*.test.ts', '!./demo.ts', '!./demoScenarios.ts', '!../components/demo/**', '!../api/schema.d.ts'],
  { query: '?raw', import: 'default', eager: true },
)
const CORPUS = Object.values(SOURCES).join('\n')

describe('시연 시나리오 정의', () => {
  it('세 시나리오, id가 겹치지 않고 이름·설명·필요한 설계변경이 있음', () => {
    expect(DEMO_SCENARIOS).toHaveLength(3)
    expect(new Set(DEMO_SCENARIOS.map((s) => s.id)).size).toBe(DEMO_SCENARIOS.length)
    for (const scenario of DEMO_SCENARIOS) {
      expect(scenario.name.trim()).not.toBe('')
      expect(scenario.summary.trim()).not.toBe('')
      expect(scenario.needs.length).toBeGreaterThan(0)
      expect(scenario.needs.every((id) => /^ECN-[A-Z]-\d{4}$/.test(id))).toBe(true)
    }
  })

  it('단계마다 안내 문구와 비지 않은 셀렉터가 있음', () => {
    for (const { step } of steps) {
      expect(step.caption.trim(), step.target).not.toBe('')
      expect(step.target.trim()).not.toBe('')
      if (step.focus !== undefined) expect(step.focus.trim()).not.toBe('')
      if (step.text !== undefined) expect(step.text.trim()).not.toBe('')
      if (step.waitFor) {
        expect(step.waitFor.target.trim()).not.toBe('')
        expect(step.waitFor.timeout ?? 1).toBeGreaterThan(0)
      }
      if (step.skipIf) expect(step.skipIf.target.trim()).not.toBe('')
    }
  })

  it('띠에 나오는 문구는 명사형(…요·…니다·마침표로 끝나지 않음)', () => {
    for (const { step } of steps.filter(({ step }) => !step.quiet)) expect(step.caption, step.caption).not.toMatch(/요$|니다$|\.$/)
  })

  it('데이터를 바꾸는 동작이 없음(기록·검토 요청·결재·통보·지도 바꾸기)', () => {
    for (const { step } of steps) expect(unsafeReason(step), `${step.target} ${step.text ?? ''}`).toBeNull()
    for (const { step } of steps.filter(({ step }) => step.action === 'type')) {
      expect(step.target).toBe(S.input)
      expect(step.value?.trim()).toBeTruthy()
    }
  })

  it('단계마다 1.5~3초 머물고, 분석 대기를 빼고 시나리오 하나가 30~60초', () => {
    for (const { step } of steps.filter(({ step }) => !step.quiet)) {
      const hold = step.hold ?? DEFAULT_HOLD
      expect(hold).toBeGreaterThanOrEqual(1500)
      expect(hold).toBeLessThanOrEqual(3000)
    }
    for (const scenario of DEMO_SCENARIOS) {
      expect(estimateMs(scenario), scenario.id).toBeGreaterThanOrEqual(30000)
      expect(estimateMs(scenario), scenario.id).toBeLessThanOrEqual(60000)
    }
  })

  it('가정 계산으로 바뀐 점 띠를 띄우면 끝나기 전에 되돌리고, 마지막에는 처음 설계변경을 다시 연다', () => {
    for (const scenario of DEMO_SCENARIOS) {
      const shown = scenario.steps.findIndex((step) => step.waitFor?.target === S.changes && !step.waitFor.gone)
      if (shown >= 0) {
        const undo = scenario.steps.findIndex((step, i) => i > shown && step.target === S.changesButton && step.text === '되돌리기')
        expect(undo, scenario.id).toBeGreaterThan(shown)
      }
      const counted = scenario.steps.filter((step) => !step.quiet)
      const last = counted[counted.length - 1]
      expect(last.target, scenario.id).toBe(S.row)
      expect(last.text, scenario.id).toBe(scenario.needs[0])
      expect(last.optional, scenario.id).toBeFalsy()
    }
  })

  it('목록에서 설계변경을 여는 단계는 그 번호가 뜨고 다시 계산을 마칠 때까지 기다림(같은 건을 다시 열 때도)', () => {
    const opens = steps.filter(({ step }) => step.target === S.row)
    expect(opens.length).toBeGreaterThan(0)
    for (const { step } of opens) {
      expect(step.waitFor?.target).toBe(S.shownEcn)
      expect(step.waitFor?.text).toBe(step.text)
    }
    expect(S.shownEcn).toContain(':not(:has(> [role="status"] > *))')
  })

  it('분석·계산을 오래 기다리는 결과는 오류 알림이 뜨면 바로 멈춤(제한 시간 내내 멈춘 화면 없음)', () => {
    const long = steps.filter(({ step }) => step.waitFor && !step.waitFor.gone && (step.waitFor.timeout ?? 0) >= 20000)
    expect(long.length).toBeGreaterThan(0)
    for (const { step } of long) expect(step.waitFor?.failIf, step.target).toBeTruthy()
  })

  it('비서에 보내면 분석이 상세에 열린 답을 기다리고, 되묻는 답이 오면 바로 멈춤', () => {
    const sends = steps.filter(({ step }) => step.target === S.send)
    expect(sends).toHaveLength(1)
    const want = sends[0].step.waitFor
    expect(want?.target).toBe(S.analyzedReply)
    expect(want?.fresh).toBe(true)
    expect(want?.failIf).toContain(S.questionReply)
    expect(want?.failIf).toContain(S.assistantError)
  })

  it('누르는 단계는 모두 허용 목록의 단추(글 일치 방식까지 같게)', () => {
    const pressed = steps.filter(({ step }) => step.action === 'click' || step.action === 'tab')
    expect(pressed.length).toBeGreaterThan(0)
    for (const { step } of pressed) {
      const known = SAFE_CONTROLS.some(
        (c) => c.target === step.target && (c.text === undefined || c.text === step.text) && Boolean(c.exact) === Boolean(step.exact),
      )
      expect(known, `${step.target} ${step.text ?? ''}`).toBe(true)
    }
  })
})

describe('시나리오가 쓰는 이름이 화면 소스에 있음(testid·aria-label·data 속성·단추 글)', () => {
  const selectors = [
    ...Object.values(S),
    ...steps.flatMap(({ step }) => [step.target, step.focus, step.waitFor?.target, step.waitFor?.failIf]),
  ].filter((part): part is string => Boolean(part))
  const all = (pattern: RegExp) => [...new Set(selectors.flatMap((s) => [...s.matchAll(pattern)].map((m) => m[1])))]
  const quoted = (value: string) => ['"', "'", '`'].some((q) => CORPUS.includes(`${q}${value}${q}`))

  it('소스를 읽었음', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
    expect(Object.keys(SOURCES).some((path) => path.includes('components/demo'))).toBe(false)
  })

  it('data-testid', () => {
    const ids = all(/data-testid="([^"]+)"/g)
    expect(ids).toEqual(expect.arrayContaining(['detail-ecn', 'deadline-apply', 'impact-map', 'todo-actions']))
    for (const id of ids) expect(CORPUS.includes(`data-testid="${id}"`), id).toBe(true)
    // 검사가 없는 이름을 걸러 내는지(시연 코드를 소스에서 뺐으므로 시나리오에만 있는 이름은 안 보여야 한다)
    expect(CORPUS.includes('data-testid="demo-band"')).toBe(false)
  })

  it('aria-label', () => {
    const labels = all(/aria-label\^?="([^"]+)"/g)
    expect(labels.length).toBeGreaterThan(5)
    for (const label of labels) expect(quoted(label), label).toBe(true)
  })

  it('data 속성 이름과 id 앞머리', () => {
    for (const name of all(/\[(data-[a-z-]+)/g)) {
      if (name === 'data-testid') continue
      expect(CORPUS.includes(name), name).toBe(true)
    }
    for (const prefix of all(/\[id\^="([^"]+)"\]/g)) expect(CORPUS.includes(prefix), prefix).toBe(true)
  })

  it('우리 화면이 그리는 역할(Radix가 그리는 tab·tabpanel·dialog는 뺌)', () => {
    for (const role of all(/role="([^"]+)"/g).filter((r) => !['tab', 'tabpanel', 'dialog'].includes(r))) {
      expect(CORPUS.includes(`role="${role}"`), role).toBe(true)
    }
  })

  it('단계가 찾는 단추 글·결과 글', () => {
    const texts = [
      ...steps.flatMap(({ step }) => [step.text, step.waitFor?.text]),
      ...SAFE_CONTROLS.map((control) => control.text),
    ].filter((text): text is string => Boolean(text) && !/^ECN-/.test(text ?? ''))
    expect(texts.length).toBeGreaterThan(5)
    for (const text of new Set(texts)) expect(CORPUS.includes(text), text).toBe(true)
  })
})

describe('unsafeReason', () => {
  const click = (target: string, text?: string): DemoStep => ({ action: 'click', target, text, caption: '눌러요' })

  it('검토 요청·결재·통보·지도 전환 단추를 막음', () => {
    expect(unsafeReason(click('[data-testid="review-submit"]'))).not.toBeNull()
    expect(unsafeReason(click('[data-testid="approval-band"] button', '검토 요청'))).not.toBeNull()
    expect(unsafeReason(click('[data-testid="decision-submit"]'))).not.toBeNull()
    expect(unsafeReason(click('[data-testid="notice-sent"]'))).not.toBeNull()
    expect(unsafeReason(click('[data-testid="status-upload"]'))).not.toBeNull()
    expect(unsafeReason(click('button', '이 지도로 전환'))).not.toBeNull()
  })

  it('결과를 기다리는 셀렉터에 들어가도 막음', () => {
    const step: DemoStep = { ...click(S.row, 'ECN-D-0043'), waitFor: { target: '[data-testid="review-dialog"]' } }
    expect(unsafeReason(step)).not.toBeNull()
  })

  it('허용 목록에 없는 단추·다른 입력 칸은 막음', () => {
    expect(unsafeReason(click('button', '삭제'))).toBe('시연이 누를 수 없는 단추')
    expect(unsafeReason(click(S.todoButton, '보류 빼기'))).toBe('시연이 누를 수 없는 단추')
    expect(unsafeReason({ action: 'type', target: 'input[type="date"]', value: '2026-11-01', caption: '적어요' })).toBe(
      '글은 AI 비서 입력 칸에만',
    )
  })

  it("'새 대화'는 비서 칸 안에서 글이 정확히 같을 때만(부분 일치로는 못 누름)", () => {
    expect(unsafeReason({ ...click(S.newChat, '새 대화'), exact: true })).toBeNull()
    expect(unsafeReason(click(S.newChat, '새 대화'))).toBe('시연이 누를 수 없는 단추')
    expect(unsafeReason({ ...click('button', '새 대화'), exact: true })).toBe('시연이 누를 수 없는 단추')
  })

  it('보기만 하는 단계(스크롤·기다리기)는 허용 목록 없이도 됨', () => {
    expect(unsafeReason({ action: 'scroll', target: '[aria-label="핵심 수치"]', caption: '봐요' })).toBeNull()
    expect(unsafeReason({ action: 'wait', target: 'main p', text: 'ECN-D-0001', caption: '기다려요' })).toBeNull()
  })
})

describe('progressFrom', () => {
  it('건너뛴 단계는 전체에서 빠지고, 번호는 1부터 하나씩 늘어 마지막에 전체와 같음', () => {
    for (const scenario of DEMO_SCENARIOS) {
      const counted = countedSteps(scenario.steps)
      // 꼭 하는 단계는 모두 보이고 optional 단계는 모두 건너뛰는 가장 나쁜 날
      let shown = 0
      let skipped = 0
      let previous = 0
      for (const step of scenario.steps.filter((s) => !s.quiet)) {
        if (step.optional || step.skipIf) {
          skipped += 1
          continue
        }
        const { n, total } = progressFrom(counted, shown, skipped)
        expect(n).toBe(previous + 1)
        expect(n).toBeLessThanOrEqual(total)
        previous = n
        shown += 1
      }
      expect(previous).toBe(progressFrom(counted, shown - 1, skipped).total)
    }
  })

  it('예: 11단계 중 하나를 건너뛰면 3/11 다음이 4/10', () => {
    expect(progressFrom(11, 2, 0)).toEqual({ n: 3, total: 11 })
    expect(progressFrom(11, 3, 1)).toEqual({ n: 4, total: 10 })
    expect(progressFrom(11, 9, 1)).toEqual({ n: 10, total: 10 })
  })

  it('준비 단계는 세지 않음', () => {
    const quiet: DemoStep = { action: 'click', target: S.listOpen, caption: '펴요', quiet: true }
    const shown: DemoStep = { action: 'scroll', target: S.keyNumbers, caption: '봐요' }
    expect(countedSteps([quiet, shown, shown])).toBe(2)
  })
})

describe('progressCounter — 실행기가 도는 동안의 번호 세기', () => {
  it('show는 progressFrom과 같은 번호를 주며 세고, skip은 준비 단계를 빼고 셈', () => {
    const shown: DemoStep = { action: 'scroll', target: S.keyNumbers, caption: '봐요' }
    const optional: DemoStep = { ...shown, optional: true }
    const quiet: DemoStep = { ...shown, quiet: true, optional: true }
    const counter = progressCounter([shown, optional, quiet, shown, shown])
    expect(counter.show()).toEqual(progressFrom(4, 0, 0))
    counter.skip(quiet) // 준비 단계는 세지 않음
    expect(counter.show()).toEqual({ n: 2, total: 4 })
    counter.skip(optional)
    expect(counter.show()).toEqual({ n: 3, total: 3 })
    expect(counter.show()).toEqual({ n: 3, total: 3 }) // 넘쳐도 전체를 넘지 않음
  })

  it('시나리오마다 실행기 순서(건너뛰기·보이기)대로 세면 progressFrom 손 계산과 같음', () => {
    for (const scenario of DEMO_SCENARIOS) {
      const counter = progressCounter(scenario.steps)
      const counted = countedSteps(scenario.steps)
      let shown = 0
      let skipped = 0
      for (const step of scenario.steps) {
        if (step.optional) {
          counter.skip(step)
          if (!step.quiet) skipped += 1
          continue
        }
        if (captionWhen(step) === 'never') continue
        expect(counter.show(), scenario.id).toEqual(progressFrom(counted, shown, skipped))
        shown += 1
      }
    }
  })
})

describe('단계 판단(실행기의 순수 부분)', () => {
  const step = (extra: Partial<DemoStep>): DemoStep => ({ action: 'scroll', target: S.keyNumbers, caption: '봐요', ...extra })

  it('touches: 누르기·탭·글 넣기만, presses: 누르기·탭만', () => {
    const actions: DemoAction[] = ['click', 'tab', 'type', 'scroll', 'wait']
    expect(actions.map((action) => touches(step({ action })))).toEqual([true, true, true, false, false])
    expect(actions.map((action) => presses(step({ action })))).toEqual([true, true, false, false, false])
  })

  it('findTimeout: 꼭 하는 단계는 길게, optional은 짧게, 준비 optional은 더 짧게', () => {
    expect(findTimeout(step({}))).toBe(FIND_TIMEOUT)
    expect(findTimeout(step({ quiet: true }))).toBe(FIND_TIMEOUT)
    expect(findTimeout(step({ optional: true }))).toBe(OPTIONAL_STEP_WAIT)
    expect(findTimeout(step({ optional: true, quiet: true }))).toBe(OPTIONAL_WAIT)
    expect(OPTIONAL_WAIT).toBeLessThan(OPTIONAL_STEP_WAIT)
    expect(OPTIONAL_STEP_WAIT).toBeLessThan(FIND_TIMEOUT)
  })

  it('captionWhen: 꼭 하는 단계는 기다리기 전, optional은 찾은 뒤, 준비 단계는 내지 않음', () => {
    expect(captionWhen(step({}))).toBe('before')
    expect(captionWhen(step({ optional: true }))).toBe('found')
    expect(captionWhen(step({ quiet: true }))).toBe('never')
    expect(captionWhen(step({ quiet: true, optional: true }))).toBe('never')
  })

  it('revealBlock: 번호 단계는 기본 가운데, 준비 스크롤은 기본 위끝, 준비 누르기는 옮기지 않음', () => {
    expect(revealBlock(step({}))).toBe('center')
    expect(revealBlock(step({ block: 'start' }))).toBe('start')
    expect(revealBlock(step({ action: 'click' }))).toBe('center')
    expect(revealBlock(step({ quiet: true }))).toBe('start')
    expect(revealBlock(step({ quiet: true, block: 'center' }))).toBe('center')
    expect(revealBlock(step({ quiet: true, action: 'click' }))).toBeNull()
    expect(revealBlock(step({ quiet: true, action: 'tab', block: 'start' }))).toBeNull()
  })

  it('leadMs: 번호 단계가 요소에 손을 댈 때만 읽을 틈', () => {
    expect(leadMs(step({ action: 'click' }))).toBe(LEAD_MS)
    expect(leadMs(step({ action: 'type', value: '글' }))).toBe(LEAD_MS)
    expect(leadMs(step({}))).toBe(0)
    expect(leadMs(step({ action: 'click', quiet: true }))).toBe(0)
  })

  it('targetLabel: 셀렉터와 찾는 글', () => {
    expect(targetLabel({ target: S.row, text: 'ECN-D-0043' })).toBe(`${S.row} ECN-D-0043`)
    expect(targetLabel({ target: S.row })).toBe(`${S.row} `)
  })

  it('isSafeControl: 셀렉터·글·글 일치 방식이 모두 맞아야 허용(허용 목록의 각 항목은 자기 자신으로 허용)', () => {
    for (const control of SAFE_CONTROLS) expect(isSafeControl(control), `${control.target} ${control.text ?? ''}`).toBe(true)
    expect(isSafeControl({ target: S.row, text: 'ECN-D-0043' })).toBe(true) // 글 없는 항목은 어떤 글이든
    expect(isSafeControl({ target: S.todoButton, text: '보류 빼기' })).toBe(false)
    expect(isSafeControl({ target: S.newChat, text: '새 대화' })).toBe(false)
    expect(isSafeControl({ target: 'button' })).toBe(false)
  })
})

describe('띠·메뉴 도우미', () => {
  it('띠 이름', () => {
    expect(bandLabel(2, 7)).toBe('시연 · 2/7')
  })

  it('띠 본문: 도는 중은 단계 문구, 막힘·마침은 고정 문구', () => {
    expect(bandText('running', '목록을 펼쳐요')).toBe('목록을 펼쳐요')
    expect(bandText('stuck', '목록을 펼쳐요')).toBe(STUCK_TEXT)
    expect(bandText('done', '목록을 펼쳐요')).toBe(DONE_TEXT)
  })

  it('지도에 필요한 설계변경이 모두 있어야 돌릴 수 있음', () => {
    const [first] = DEMO_SCENARIOS
    expect(scenarioReady(first, new Set(first.needs))).toBe(true)
    expect(scenarioReady(first, new Set(['ECN-D-9999']))).toBe(false)
    expect(scenarioReady(first, new Set())).toBe(false)
  })

  it('조합 키만 누른 것은 멈추지 않음', () => {
    expect(stopsOnKey('Escape')).toBe(true)
    expect(stopsOnKey('a')).toBe(true)
    expect(stopsOnKey('PageDown')).toBe(true)
    expect(stopsOnKey('Shift')).toBe(false)
    expect(stopsOnKey('Control')).toBe(false)
  })
})
