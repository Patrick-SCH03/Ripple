// 메신저용 요약(팀 단톡방·사내 메신저에 붙여 넣는 몇 줄): 판정·이유 → 총변경비용 → 추가 공수·재료비(1.35.0) → 결정 기한 →
// 일정 지연 → 할 일.
// 숫자는 모두 분석 결과에서 오고(핵심 수치 카드와 같은 표기), 공식 메일(lib/mail.ts)과 달리 인사·서명 없이 짧게 쓴다.
import type { AnalysisResult } from '@/api/client'
import { approvalHoldShort } from './approvalHold'
import { daysBetween, formatDay } from './format'
import { VERDICT_NAMES } from './labels'
import { formatMoney, formatRange } from './money'
import { causeName } from './request'
import { splitLine } from './costSplit'
import { keyNumbers, todoText, todos } from './summary'

/** 할 일(조치)은 이만큼만 적고 나머지는 '외 n건'. */
const BRIEF_TODOS = 3

function deadlineLine(result: AnalysisResult): string {
  const { kind, last_day: lastDay } = result.timing.deadline
  if (kind === 'confirm_now') return '결정 기한: 오늘 확정 필요(내일부터 추가손실)'
  if (kind === 'none_in_horizon') return `결정 기한: 기간 안 없음(${formatDay(lastDay)}까지 추가손실 없음)`
  const days = daysBetween(result.request.as_of, lastDay) ?? 0
  return `결정 기한: ${formatDay(lastDay)}(D-${days})`
}

export function briefingText(result: AnalysisResult): string {
  const { change } = result.request
  const head = [change.ecn_id, change.title].filter(Boolean).join(' ')
  const lines = [`[설계변경] ${head || '설계변경'}`]
  if (change.cause) lines.push(`변경 원인: ${causeName(change.cause)}`)
  if (result.request.outfit_on_board) lines.push('실행 방식: 후행 설치(탑재 뒤 선상에서 설치)')
  const reasons = result.verdict.reasons.join(' · ')
  lines.push(`판정: ${VERDICT_NAMES[result.verdict.level]}${reasons ? ` — ${reasons}` : ''}`)
  const { total } = result
  const range = total.low === total.high ? '' : `(${formatRange(total.low, total.high)})`
  lines.push(`총변경비용: ${formatMoney(total.value)}${range}`)
  // 1.35.0 구분: 추가 공수 · 재료비 한 줄(결정 도우미 세 줄 요약과 같은 고정 문장, lib/costSplit splitLine)
  const split = splitLine(result)
  if (split) lines.push(split)
  lines.push(deadlineLine(result))
  // 일정 줄은 핵심 수치 카드와 같은 값·주의(자재가 늦게 오면 최대 n일 · 지체상금)를 쓴다
  for (const card of keyNumbers(result)) {
    if (card.id === 'exit') {
      const notes = [card.caution, card.outside].filter(Boolean).join(' · ')
      lines.push(`구역 출구 최대 지연: ${card.value}${notes ? `(${notes})` : ''}`)
    }
    if (card.id === 'delivery') {
      const notes = [card.detail, card.caution].filter(Boolean).join(' · ')
      lines.push(`늘어난 인도 지연: ${card.value}${notes ? `(${notes})` : ''}`)
    }
  }
  // 적용한 보류는 실제 발주가 아니라 가정 계산이라 그렇게 적는다(단톡방에서 실제 보류로 읽히지 않게).
  // 보류 권고는 결재 기간 꼬리를 붙인다(결재 중엔 보류 가능 · 권고 기간까지는 공급사 협의, lib/approvalHold)
  const items = todos(result).map((todo) => {
    const title = todoText(todo, result.timing.deadline).title
    if (todo.kind === 'held') return `${title}(가정 계산)`
    const short = todo.kind === 'hold' ? approvalHoldShort(todo.advice, result.approval_plan) : null
    if (todo.kind === 'hold' && short) return `${title}(${short})`
    return title
  })
  if (items.length > 0) {
    const shown = items.slice(0, BRIEF_TODOS).join(' · ')
    const rest = items.length > BRIEF_TODOS ? ` 외 ${items.length - BRIEF_TODOS}건` : ''
    lines.push(`할 일: ${shown}${rest}`)
  }
  lines.push(`(Ripple 분석 · 기준일 ${formatDay(result.request.as_of)})`)
  return lines.join('\n')
}
