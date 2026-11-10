// 나타나는 묶음(DESIGN.md 12절 움직임). Reveal = 스크롤해 화면에 들어오면 아래에서 살짝 떠오르며(한 번만, 0.6초),
// Rise = 첫 화면이라 불러오자마자 같은 모양으로(스크립트·관찰기를 기다리지 않는 CSS 움직임 — 첫 화면이 비어 보이지 않게).
// 움직임 줄이기면 둘 다 처음부터 보인다(motion.ts · landing.css).
import type { CSSProperties, ReactNode } from 'react'
import { useInView } from './motion'

function delayStyle(delay: number): CSSProperties | undefined {
  return delay ? ({ '--rp-delay': `${delay}ms` } as CSSProperties) : undefined
}

export function Rise({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <div className={`rp-rise${className ? ` ${className}` : ''}`} style={delayStyle(delay)}>
      {children}
    </div>
  )
}

interface Props {
  children: ReactNode
  /** 목록 안이면 'li'. */
  as?: 'div' | 'li'
  /** 같은 줄 항목을 차례로 띄울 때의 지연(ms). */
  delay?: number
  className?: string
}

export function Reveal({ children, as = 'div', delay = 0, className }: Props) {
  const [ref, shown] = useInView<HTMLElement>()
  const props = {
    ref,
    className: `rp-reveal${className ? ` ${className}` : ''}`,
    'data-shown': shown ? 'true' : 'false',
    style: delayStyle(delay),
  }
  return as === 'li' ? <li {...props}>{children}</li> : <div {...props}>{children}</div>
}
