// 금액 표기(DESIGN.md 8절). 첫 화면은 만원 반올림("298만원", 1억 이상은 "2억 2,421만원"), 근거 펼침은 원 단위
// ("2,984,205원"). 음수는 "절감 12만원". 값은 엔진이 원 단위로 반올림한 정수다.
const MAN = 10_000
const MAN_PER_EOK = 10_000

/** 세 자리 쉼표(로캘에 기대지 않음). */
function grouped(n: number): string {
  return String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** 원 단위: 2984205 → "2,984,205원", -12000 → "−12,000원". */
export function formatWon(won: number): string {
  return `${won < 0 ? '−' : ''}${grouped(Math.abs(won))}원`
}

/** 만원 반올림한 양수의 글자(단위 '원' 없이): 2984205 → "298만", 224214705 → "2억 2,421만", 200000000 → "2억". */
function manwon(won: number): string {
  const man = Math.round(won / MAN)
  const eok = Math.floor(man / MAN_PER_EOK)
  const rest = man % MAN_PER_EOK
  if (eok === 0) return `${grouped(rest)}만`
  return rest === 0 ? `${grouped(eok)}억` : `${grouped(eok)}억 ${grouped(rest)}만`
}

/** 첫 화면 금액: 1만원 미만은 원 그대로, 그 위는 만원 반올림, 음수는 '절감'. */
export function formatMoney(won: number): string {
  if (won < 0) return `절감 ${formatMoney(-won)}`
  if (won < MAN) return formatWon(won)
  return `${manwon(won)}원`
}

/** 금액 범위: "66만~789만원". 끝이 1만원 미만이거나 음수면 끝마다 단위를 붙인다("8,500원~12만원", "−12만원~789만원"). */
export function formatRange(low: number, high: number): string {
  if (low >= MAN && high >= MAN) return `${manwon(low)}~${manwon(high)}원`
  const end = (won: number) => (won < 0 ? `−${formatMoney(-won)}` : formatMoney(won))
  return `${end(low)}~${end(high)}`
}

/** 축 눈금처럼 짧게: 0 → "0", 1만원 미만은 "0.9만"처럼 소수 한 자리, 그 위는 만원 반올림("298만", "2.2억"). */
export function formatAxis(won: number): string {
  const sign = won < 0 ? '−' : ''
  const abs = Math.abs(won)
  if (abs === 0) return '0'
  if (abs >= MAN * MAN_PER_EOK) return `${sign}${(abs / (MAN * MAN_PER_EOK)).toFixed(1).replace(/\.0$/, '')}억`
  if (abs < MAN) return `${sign}${(abs / MAN).toFixed(1)}만`
  return `${sign}${grouped(Math.round(abs / MAN))}만`
}
