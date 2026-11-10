// 영향 지도 카드·연결을 React Flow 노드·간선으로 옮긴다(그리기 값만 — 위치·묶음·주요 경로는 lib/graphModel이 정한다).
// 단계별 나타나기(STEP_MS 간격), '주요 경로만'이면 경로 밖을 흐리게, 주요 경로 간선은 흐르는 점선.
import { type Edge, MarkerType } from '@xyflow/react'
import type { CSSProperties } from 'react'
import type { ImpactView } from '@/api/client'
import { cardText, type GraphModel, type MainPaths } from '@/lib/graphModel'
import { RELATION_NAMES, SEVERITY_NAMES, nameOf } from '@/lib/labels'
import type { CardNode } from './FlowCards'

/** 단계(열) 하나가 나타나는 간격(ms). */
export const STEP_MS = 520

interface Anim {
  name: string
  duration: string
  timing: string
  delay: string
  count: string
  fill: string
  play: string
}

/** 애니메이션 여럿을 낱개 속성으로 펼친다(React는 animation 줄임말과 animationPlayState를 섞어 쓰면 경고한다). */
function animationStyle(list: readonly Anim[]): CSSProperties {
  if (list.length === 0) return {}
  const join = (key: keyof Anim) => list.map((anim) => anim[key]).join(', ')
  return {
    animationName: join('name'),
    animationDuration: join('duration'),
    animationTimingFunction: join('timing'),
    animationDelay: join('delay'),
    animationIterationCount: join('count'),
    animationFillMode: join('fill'),
    animationPlayState: join('play'),
  }
}

interface NodeOptions {
  selected: string | null
  motion: boolean
  focusMain: boolean
  onExpand: (groupId: string) => void
}

export function cardNodes(
  report: ImpactView,
  model: GraphModel,
  main: MainPaths,
  { selected, motion, focusMain, onExpand }: NodeOptions,
): CardNode[] {
  return model.cards.map((card) => {
    const { title, meta } = cardText(report, card)
    return {
      id: card.id,
      type: 'card',
      position: { x: card.x, y: card.y },
      width: card.width,
      height: card.height,
      draggable: false,
      selectable: false,
      // '주요 경로만'이면 경로 밖 카드를 흐리게(카드 안은 나타나기 애니메이션이 투명도를 쥐고 있어 바깥 감싸개에 건다)
      style: { opacity: focusMain && !main.cards.has(card.id) ? 0.22 : 1, transition: 'opacity 300ms' },
      ariaLabel: `${title}, ${meta}${card.severity ? `, 영향 ${SEVERITY_NAMES[card.severity]}` : ''}${main.peaks.has(card.id) ? ', 주요 영향' : ''}`,
      data: {
        card,
        title,
        meta,
        delay: card.layer * STEP_MS,
        current: card.id === selected,
        peak: main.peaks.has(card.id),
        moving: motion,
        onExpand,
      },
    }
  })
}

interface EdgeOptions {
  selected: string | null
  motion: boolean
  focusMain: boolean
  /** 처음 등장이 끝났나(끝나면 나타나기 애니메이션을 간선에서 뺀다). */
  settled: boolean
}

export function linkEdges(
  model: GraphModel,
  main: MainPaths,
  { selected, motion, focusMain, settled }: EdgeOptions,
): Edge[] {
  return model.links.map((link) => {
    const touching = selected !== null && (link.source === selected || link.target === selected)
    const key = main.links.has(link.id)
    const color = key ? 'var(--danger)' : link.virtual ? 'var(--primary)' : 'var(--border-strong)'
    const delay = (model.cards.find((c) => c.id === link.target)?.layer ?? 0) * STEP_MS
    const appear: Anim = { name: 'ripple-appear', duration: '380ms', timing: 'ease-out', delay: `${delay}ms`, count: '1', fill: 'both', play: 'running' }
    const flowing: Anim = {
      name: 'rp-flow',
      duration: '1s',
      timing: 'linear',
      delay: `${settled ? 0 : delay + 380}ms`,
      count: 'infinite',
      fill: 'none',
      play: motion ? 'running' : 'paused',
    }
    const anims = settled ? (key ? [flowing] : []) : key ? [appear, flowing] : [appear]
    return {
      id: link.id,
      source: link.source,
      target: link.target,
      focusable: false,
      selectable: false,
      style: {
        stroke: color,
        strokeWidth: key ? 2.25 : touching ? 2 : 1.5,
        // 주요 경로는 흐르는 점선, 변경으로 생긴 연결은 고정 점선. 움직임은 재생·멈춤만 바꾼다(애니메이션 목록을
        // 바꾸면 나타나기까지 처음부터 다시 돌아 간선이 깜빡인다)
        strokeDasharray: key ? '7 5' : link.virtual ? '6 4' : undefined,
        opacity: focusMain && !key ? 0.18 : 1,
        transition: 'opacity 300ms',
        ...animationStyle(anims),
      },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      // 관계 이름은 고른 카드에 닿은 간선에만(평소에는 근거 패널의 경로로 본다)
      label: touching ? `${nameOf(RELATION_NAMES, link.relation)}${link.count > 1 ? ` ${link.count}` : ''}` : undefined,
      labelStyle: { fill: 'var(--text-secondary)', fontSize: 13 },
      labelBgStyle: { fill: 'var(--surface)' },
      labelBgPadding: [4, 2] as [number, number],
    }
  })
}
