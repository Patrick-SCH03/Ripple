// 소개 화면 끝 묶음: 운영 조건(밤색 판 — 운영 조건 한 줄 띠 + 잰 값 3개) · 마지막 권유 판. 홍보 페이지라 설명 문단은 두지 않는다.
// 글은 content.ts, 숫자는 잰 값(MEASURED)만.
import type { CSSProperties, ReactNode } from 'react'
import { MEASURED, TRUST, type Measured } from './content'
import { FULL, TITLE } from './layout'
import { useCountUp, useInView } from './motion'
import { Reveal } from './Reveal'

/** 운영 조건 한 줄 띠: 아이콘 + 짧은 명사구. 넓으면 한 줄, 좁으면 위아래. */
export function TrustBand() {
  return (
    <ul className="flex flex-col gap-4 md:flex-row md:flex-wrap md:justify-center md:gap-x-10">
      {TRUST.map((item) => (
        <li key={item.text} className="flex items-center gap-3">
          <span className="rp-night-tile flex size-10 shrink-0 items-center justify-center rounded-[12px]">
            <item.icon aria-hidden className="rp-night-accent size-5" />
          </span>
          <span className="text-lead font-semibold">{item.text}</span>
        </li>
      ))}
    </ul>
  )
}

export function MeasuredList() {
  return (
    <dl className="grid gap-12 md:grid-cols-3 md:gap-8">
      {MEASURED.map((item, i) => (
        <MeasuredItem key={item.label} item={item} delay={i * 100} />
      ))}
    </dl>
  )
}

/**
 * 잰 값 하나: 화면에 들어오면 숫자가 0부터 올라간다. 자리는 끝 값 폭으로 잡아 두고(흔들림 없게 — 글자가 아닌 ::before라
 * 복사·찾기에 끝 값이 겹쳐 잡히지 않는다), 읽기 프로그램에는 끝 값. 아래 이름.
 */
function MeasuredItem({ item, delay }: { item: Measured; delay: number }) {
  const [ref, inView] = useInView<HTMLDivElement>()
  const shown = useCountUp(item.value, inView)
  return (
    <div
      ref={ref}
      className="rp-reveal flex flex-col items-center text-center"
      data-shown={inView ? 'true' : 'false'}
      style={delay ? ({ '--rp-delay': `${delay}ms` } as CSSProperties) : undefined}
    >
      <dt className="order-2 mt-3 text-item font-bold tracking-tight">{item.label}</dt>
      <dd className="order-1 text-display-md font-bold tracking-tight whitespace-nowrap tabular-nums lg:text-display">
        <span aria-hidden className="rp-count" data-final={item.value}>
          <span>{shown}</span>
        </span>
        <span className="sr-only">{item.value}</span>
      </dd>
    </div>
  )
}

/** 마지막 권유 판(파란 바탕): 첫 화면 단추 짝을 한 번 더. */
export function EndCall({ actions }: { actions: ReactNode }) {
  return (
    <section aria-labelledby="end-title" className="py-20 lg:py-28">
      <div className={FULL}>
        <Reveal className="rp-cta flex flex-col items-center rounded-[28px] px-6 py-24 text-center sm:px-10 lg:py-36">
          <h2 id="end-title" className={TITLE}>
            다음 설계변경,
            <br /> 확정 전에 영향 범위부터
          </h2>
          <div className="mt-10 w-full sm:w-auto">{actions}</div>
        </Reveal>
      </div>
    </section>
  )
}
