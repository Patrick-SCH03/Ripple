// 파급 그림(소개 화면 첫 화면): 바뀐 부재에서 물결이 퍼지듯 영향이 첫 고리(바로 이어진 곳) → 두 번째 고리(그 카드를 거쳐
// 번진 곳)로 차례로 나타난다. 이름·금액은 엔진 출력(example.json). 넓으면 SVG, 좁으면(640px 미만) 들여쓴 목록.
// animate가 거짓이면(다 그려진 뒤·움직임 줄이기) 움직임 클래스를 떼어 정지 그림으로 둔다 — 창 크기를 바꾸거나 숨었던 목록이
// 다시 보여도 처음부터 다시 그리지 않게.
import { SHOWCASE, changeText, nodeText, rings, type ShowcaseNode } from './example'
import { SEVERITY_COLOR as SEVERITY_STROKE, SEVERITY_WORD } from './severity'

const VIEW = { width: 760, height: 420 }
const CHANGE = { x: 12, y: 172, w: 216, h: 76 }
const FIRST = { x: 300, w: 214, h: 62, gap: 78 }
const SECOND = { x: 556, w: 196, h: 62 }
const ORIGIN = { x: CHANGE.x + CHANGE.w / 2, y: CHANGE.y + CHANGE.h / 2 }

function curve(x1: number, y1: number, x2: number, y2: number): string {
  const mid = (x1 + x2) / 2
  return `M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`
}

interface CardProps {
  node: ShowcaseNode
  x: number
  y: number
  w: number
  h: number
  delay: number
  animate: boolean
}

function Card({ node, x, y, w, h, delay, animate }: CardProps) {
  const text = nodeText(node)
  return (
    <g
      className={animate ? 'rp-node' : undefined}
      style={animate ? { ['--d' as string]: `${delay}s` } : undefined}
      data-testid="ripple-node"
    >
      <title>{`${text.action} — ${text.subject} · ${text.amount} · 심각도 ${SEVERITY_WORD[node.severity]}`}</title>
      <rect x={x} y={y} width={w} height={h} rx={6} fill="var(--surface)" stroke={SEVERITY_STROKE[node.severity]} strokeWidth={1.5} />
      <rect x={x} y={y + 8} width={3} height={h - 16} rx={1.5} fill={SEVERITY_STROKE[node.severity]} />
      <text x={x + 14} y={y + 24} fontSize={12} fill="var(--text-secondary)">
        {text.subject}
      </text>
      <text x={x + 14} y={y + 46} fontSize={14} fontWeight={600} fill="var(--text-primary)">
        {text.action}
      </text>
      <text
        x={x + w - 12}
        y={y + 46}
        fontSize={13}
        fill="var(--text-primary)"
        textAnchor="end"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {text.amount}
      </text>
    </g>
  )
}

/** 넓은 화면: SVG 파급 그림. */
export function RippleSvg({ animate }: { animate: boolean }) {
  const { first, second } = rings(SHOWCASE.nodes)
  const change = changeText(SHOWCASE)
  const firstY = (i: number) => ORIGIN.y + (i - (first.length - 1) / 2) * FIRST.gap - FIRST.h / 2
  const firstIndex = new Map(first.map((n, i) => [n.key, i]))
  const siblings = (node: ShowcaseNode) => second.filter((n) => n.parent === node.parent)
  const secondY = (node: ShowcaseNode) => {
    const parentY = firstY(firstIndex.get(node.parent ?? '') ?? 0)
    return parentY + siblings(node).indexOf(node) * FIRST.gap
  }
  return (
    <svg
      viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
      className="h-auto w-full overflow-hidden"
      role="img"
      aria-labelledby="ripple-title"
      data-testid="ripple-svg"
    >
      <title id="ripple-title">
        {`${change.action}: 영향 ${SHOWCASE.impact_count}건이 부재·블록·발주·도면·공정으로 이어집니다`}
      </title>
      {[0, 1.2, 2.4].map((delay) => (
        <circle
          key={delay}
          className="rp-ring"
          style={{ ['--d' as string]: `${delay}s` }}
          cx={ORIGIN.x}
          cy={ORIGIN.y}
          r={330}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={1.5}
        />
      ))}
      {first.map((node, i) => (
        <path
          key={`e-${node.key}`}
          className={animate ? 'rp-edge' : undefined}
          style={animate ? { ['--d' as string]: `${0.35 + i * 0.12}s` } : undefined}
          pathLength={1}
          d={curve(CHANGE.x + CHANGE.w, ORIGIN.y, FIRST.x, firstY(i) + FIRST.h / 2)}
          fill="none"
          stroke="var(--border-strong)"
          strokeWidth={1.5}
        />
      ))}
      {second.map((node, i) => {
        const parentY = firstY(firstIndex.get(node.parent ?? '') ?? 0) + FIRST.h / 2
        return (
          <path
            key={`e-${node.key}`}
            className={animate ? 'rp-edge' : undefined}
            style={animate ? { ['--d' as string]: `${1.35 + i * 0.15}s` } : undefined}
            pathLength={1}
            d={curve(FIRST.x + FIRST.w, parentY, SECOND.x, secondY(node) + SECOND.h / 2)}
            fill="none"
            stroke="var(--border-strong)"
            strokeWidth={1.5}
          />
        )
      })}
      <g>
        <rect
          x={CHANGE.x}
          y={CHANGE.y}
          width={CHANGE.w}
          height={CHANGE.h}
          rx={6}
          fill="var(--surface)"
          stroke="var(--text-primary)"
          strokeWidth={2}
        />
        <text x={CHANGE.x + 16} y={CHANGE.y + 28} fontSize={12} fill="var(--text-secondary)">
          {change.subject}
        </text>
        <text x={CHANGE.x + 16} y={CHANGE.y + 52} fontSize={14} fontWeight={600} fill="var(--text-primary)">
          {change.action}
        </text>
      </g>
      {first.map((node, i) => (
        <Card
          key={node.key}
          node={node}
          x={FIRST.x}
          y={firstY(i)}
          w={FIRST.w}
          h={FIRST.h}
          delay={0.55 + i * 0.12}
          animate={animate}
        />
      ))}
      {second.map((node, i) => (
        <Card
          key={node.key}
          node={node}
          x={SECOND.x}
          y={secondY(node)}
          w={SECOND.w}
          h={SECOND.h}
          delay={1.55 + i * 0.15}
          animate={animate}
        />
      ))}
    </svg>
  )
}

/** 좁은 화면: 들여쓴 목록(두 번째 고리는 부모 아래로 들여씀). */
export function RippleList({ animate }: { animate: boolean }) {
  const { first, second } = rings(SHOWCASE.nodes)
  const change = changeText(SHOWCASE)
  let order = 0
  const item = (node: ShowcaseNode, nested: boolean) => {
    const text = nodeText(node)
    const delay = 0.3 + order++ * 0.1
    return (
      <li
        key={node.key}
        className={`${animate ? 'rp-node ' : ''}rounded-md border border-border bg-surface px-3 py-2 ${nested ? 'ml-6' : ''}`}
        style={{
          ...(animate ? { ['--d' as string]: `${delay}s` } : {}),
          borderLeft: `3px solid ${SEVERITY_STROKE[node.severity]}`,
        }}
      >
        <p className="text-xs text-foreground-secondary">{text.subject}</p>
        <p className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">{text.action}</span>
          <span className="text-sm tabular-nums">{text.amount}</span>
        </p>
      </li>
    )
  }
  return (
    <div data-testid="ripple-list">
      <div className="rounded-md border-2 border-foreground bg-surface px-3 py-2">
        <p className="text-xs text-foreground-secondary">{change.subject}</p>
        <p className="text-sm font-semibold">{change.action}</p>
      </div>
      <ul className="mt-2 flex flex-col gap-2 border-l border-border-strong pl-3" aria-label="영향받는 곳">
        {first.flatMap((node) => [item(node, false), ...second.filter((n) => n.parent === node.key).map((n) => item(n, true))])}
      </ul>
    </div>
  )
}
