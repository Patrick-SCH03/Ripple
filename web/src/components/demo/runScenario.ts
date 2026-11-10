// 시연 실행기: 시나리오의 단계를 차례로 — 요소가 나타날 때까지 기다리고 → 부드럽게 스크롤 → 둥근 테두리로 강조 →
// 실제 단추를 누르고 → 결과를 기다려 잠깐 보여 준다. 안내 띠·강조는 view로 알린다(useDemoRunner가 그린다).
// 단계마다 무엇을 얼마나 할지(기다림·스크롤 위치·문구 시점·번호)는 lib/demo의 순수 함수가 정하고, 여기는 흐름과 DOM만.
// 데이터를 바꾸는 단계는 lib/demo unsafeReason으로 실행 전에 한 번 더 막는다.
import {
  DEFAULT_HOLD,
  FIND_TIMEOUT,
  RENDER_MS,
  SETTLE_MS,
  TYPE_MS,
  captionWhen,
  findTimeout,
  leadMs,
  presses,
  progressCounter,
  revealBlock,
  targetLabel,
  touches,
  unsafeReason,
} from '@/lib/demo'
import type { DemoScenario, DemoStep, DemoWait } from '@/lib/demoScenarios'
import { DemoStuck, appear, findTarget, pressTab, reveal, sleep, snapshot, typeInto, vanish } from './demoDom'

/** 실행기가 화면에 알리는 것: 단계 번호·문구, 강조할 요소(누를 때 pressed). */
export interface DemoView {
  step: (n: number, total: number, caption: string) => void
  spot: (element: Element | null, pressed?: boolean) => void
}

interface Context {
  view: DemoView
  signal: AbortSignal
  reduced: boolean
}

/** 동작 전부터 화면에 있던 것: 새로 나타난 결과(fresh)·오류(failIf)만 세려고. */
interface Before {
  results?: Set<Element>
  failures?: Set<Element>
}

/** 메뉴가 닫히는 움직임이 끝난 뒤 시작. */
const START_DELAY = 250

export async function runScenario(scenario: DemoScenario, view: DemoView, signal: AbortSignal, reduced: boolean) {
  const context: Context = { view, signal, reduced }
  const progress = progressCounter(scenario.steps)
  const announce = (step: DemoStep) => {
    const { n, total } = progress.show()
    view.step(n, total, step.caption)
  }
  await sleep(START_DELAY, signal)
  for (const step of scenario.steps) {
    const reason = unsafeReason(step)
    if (reason) throw new DemoStuck(reason)
    if (step.skipIf && findTarget(step.skipIf)) {
      progress.skip(step)
      continue
    }
    const when = captionWhen(step)
    if (when === 'before') announce(step)
    const element = await locate(step, signal)
    if (!element) {
      progress.skip(step)
      continue
    }
    if (when === 'found') announce(step)
    await perform(step, element, context)
  }
  view.spot(null)
}

/** 단계의 대상: 꼭 하는 단계는 나타날 때까지(안 나오면 멈춤), optional 단계는 잠깐만 보고 없으면 null. */
async function locate(step: DemoStep, signal: AbortSignal): Promise<HTMLElement | null> {
  const element = await appear(step, { timeout: findTimeout(step), signal, usable: touches(step) })
  if (!element && !step.optional) throw new DemoStuck(`안 나옴: ${targetLabel(step)}`)
  return element
}

async function perform(step: DemoStep, element: HTMLElement, context: Context): Promise<void> {
  const { signal } = context
  const focus = (step.focus && findTarget({ target: step.focus })) || element
  await present(step, focus, context)
  // 강조·읽을 틈 동안 화면이 다시 그려져 요소가 바뀌었으면(분석이 막 끝남) 새 요소를 누른다
  const live = element.isConnected ? element : await appear(step, { timeout: FIND_TIMEOUT, signal, usable: touches(step) })
  if (!live) throw new DemoStuck(`사라짐: ${targetLabel(step)}`)
  const want = step.waitFor
  const before = beforeAction(want)
  await act(step, live, focus === element ? live : focus, context)
  if (want) {
    await sleep(RENDER_MS, signal)
    await awaitResult(step, want, context, before)
  }
  if (!step.quiet) await sleep(step.hold ?? DEFAULT_HOLD, signal)
}

/** 강조하고 화면 안으로 옮긴 뒤 읽을 틈을 준다(준비 스크롤은 강조·머무름 없이 옮기기만 — 처음 화면처럼 상세 맨 위로). */
async function present(step: DemoStep, focus: Element, { view, signal, reduced }: Context): Promise<void> {
  if (!step.quiet) view.spot(focus)
  const block = revealBlock(step)
  if (block) await reveal(focus, block, { reduced, settle: SETTLE_MS, signal })
  const lead = leadMs(step)
  if (lead > 0) await sleep(lead, signal)
}

function beforeAction(want: DemoWait | undefined): Before {
  return {
    results: want?.fresh ? snapshot(want) : undefined,
    failures: want?.failIf ? snapshot({ target: want.failIf }) : undefined,
  }
}

async function act(step: DemoStep, element: HTMLElement, focus: Element, { view, signal }: Context) {
  // 누른 순간은 강조 테두리를 한 번 깜빡인다(강조가 누른 단추 자신일 때만 — 지도 전체를 비출 때는 그대로)
  if (presses(step) && !step.quiet) view.spot(focus, focus === element)
  if (step.action === 'click') element.click()
  else if (step.action === 'tab') pressTab(element)
  else if (step.action === 'type') await typeInto(element, step.value ?? '', TYPE_MS, signal)
}

async function awaitResult(step: DemoStep, want: DemoWait, { view, signal, reduced }: Context, before: Before) {
  const timeout = want.timeout ?? FIND_TIMEOUT
  if (want.gone) {
    if (!(await vanish(want, { timeout, signal }))) throw new DemoStuck(`안 사라짐: ${want.target}`)
    return
  }
  const options = { timeout, signal, except: before.results, failIf: want.failIf, failStale: before.failures }
  const result = await appear(want, options)
  if (!result) throw new DemoStuck(`결과 안 나옴: ${targetLabel(want)}`)
  if (want.spot && !step.quiet) {
    view.spot(result)
    await reveal(result, 'center', { reduced, settle: SETTLE_MS, signal })
  }
}
