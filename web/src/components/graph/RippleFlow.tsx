// 영향 지도 그래프(React Flow): 변경 지점에서 단계별로 나타나고, 카드를 고르면 근거. 방향키로 카드 사이를 옮겨 다닌다.
// 주요 경로(가장 심각한 영향까지의 근거 경로)는 흐르는 점선 간선 + 끝 카드 맥동으로 계속 보이고(위 막대 '움직임 멈춤'으로 끔,
// 움직임 줄이기 설정이면 처음부터 멈춤), '주요 경로만'을 켜면 나머지를 흐리게 한다.
// 맞춤 보기는 읽기 하한 배율(lib/graphModel MAP_READ_ZOOM, 카드 글자 약 12~13px)을 지키고, 넘치는 긴 사슬은 변경 지점(왼쪽)부터
// 보인다 — 끌어서 나머지를 보거나 '전체 보기'(하한 없는 맞춤)로 한눈에.
// 카드 위치·묶음·주요 경로는 순수 함수(lib/graphModel)가 정하고, 여기서는 그리기와 입력만 맡는다(노드·간선 값은
// flowElements, 위 막대는 FlowToolbar).
import '@xyflow/react/dist/base.css'
import './graph.css'
import { type Edge, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { type KeyboardEvent, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import type { ImpactView } from '@/api/client'
import { type Direction, type GraphModel, cardRect, mainPaths, nearestInDirection, readableViewport } from '@/lib/graphModel'
import { safeStorage } from '@/lib/storage'
import { type CardNode, FlowCard } from './FlowCards'
import { STEP_MS, cardNodes, linkEdges } from './flowElements'
import { FlowToolbar } from './FlowToolbar'

const NODE_TYPES = { card: FlowCard }
const KEYS: Record<string, Direction> = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }
const HOW_TO = '방향키: 옆 카드로 · Enter: 근거 열기 · Esc: 선택 풀기'
// React Flow의 화면 낭독기 안내(기본은 영어, 노드 삭제·이동 안내라 이 화면과 맞지 않음)
const ARIA = {
  'node.a11yDescription.default': HOW_TO,
  'node.a11yDescription.keyboardDisabled': HOW_TO,
  'node.a11yDescription.ariaLiveMessage': () => '',
  'edge.a11yDescription.default': '카드 사이의 연결',
  'handle.ariaLabel': '연결점',
}

interface Props {
  report: ImpactView
  model: GraphModel
  /** 고른 카드 ID(엔터티 ID 또는 묶음 ID). */
  selected: string | null
  onSelect: (id: string | null) => void
  onExpand: (groupId: string) => void
  onCollapseAll: (() => void) | null
  /** 배치가 바뀐 뒤 초점을 옮길 카드(있으면 한 번 옮기고 onFocused). */
  focusTarget?: string | null
  onFocused?: () => void
  /** 전체 화면 중인가(상태는 그래프와 근거를 함께 감싼 GraphWorkspace가 든다 — 다시 보기로 그래프를 새로 그려도 유지). */
  full?: boolean
  onToggleFull?: () => void
}

const MOTION = 'ripple.map.motion'

/** 주요 경로 움직임의 처음 값: 이 브라우저에서 고른 값, 없으면 움직임 줄이기 설정이 아닐 때 켬. */
function initialMotion(): boolean {
  const saved = safeStorage.getItem(MOTION)
  if (saved === 'on' || saved === 'off') return saved === 'on'
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

interface View {
  motion: boolean
  onMotion: () => void
  focusMain: boolean
  onFocusMain: () => void
}

export function RippleFlow(props: Props) {
  const [replay, setReplay] = useState(0)
  // 움직임·주요 경로만은 다시 보기(그래프 새로 그리기)에도 그대로 두려고 바깥에서 든다
  const [motion, setMotion] = useState(initialMotion)
  const [focusMain, setFocusMain] = useState(false)
  const view: View = {
    motion,
    onMotion: () =>
      setMotion((on) => {
        safeStorage.setItem(MOTION, on ? 'off' : 'on')
        return !on
      }),
    focusMain,
    onFocusMain: () => setFocusMain((on) => !on),
  }
  return (
    <ReactFlowProvider key={replay}>
      <Flow {...props} {...view} onReplay={() => setReplay((n) => n + 1)} />
    </ReactFlowProvider>
  )
}

function Flow({
  report,
  model,
  selected,
  onSelect,
  onExpand,
  onCollapseAll,
  focusTarget,
  onFocused,
  full = false,
  onToggleFull,
  onReplay,
  motion,
  onMotion,
  focusMain,
  onFocusMain,
}: Props & View & { onReplay: () => void }) {
  const flow = useReactFlow()
  const main = useMemo(() => mainPaths(report, model), [report, model])
  // 단계별 나타나기가 끝났나: React Flow는 카드 값이 바뀌면(고르기·주요 경로만·움직임) 간선을 잠깐 지웠다 다시 만든다.
  // 그때 나타나기 애니메이션이 다시 돌면 간선이 사라졌다 나타나므로, 처음 등장이 끝난 뒤에는 간선에서 뺀다
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    const last = Math.max(0, ...model.cards.map((card) => card.layer))
    const timer = window.setTimeout(() => setSettled(true), last * STEP_MS + 500)
    return () => window.clearTimeout(timer)
  }, [model])
  const box = useRef<HTMLDivElement>(null)
  // 사용자가 직접 확대·이동했으면 칸 크기가 바뀌어도 시점을 그대로 둔다(맞춤 보기를 누르면 다시 따라간다)
  const moved = useRef(false)

  // 읽기 하한이 있는 맞춤 보기(첫 화면·맞춤 보기·칸 크기 바뀜). 넘치면 '전체 보기' 단추를 낸다
  const [overflow, setOverflow] = useState(false)
  const cards = model.cards
  // whole = 하한 없이 전체(전체 보기). 넘침 여부는 늘 읽기 하한 기준으로 잰다(전체 보기 뒤에도 단추가 남게)
  const fitReadable = useCallback(
    (duration?: number, whole = false) => {
      const element = box.current
      if (!element) return
      const panel = { width: element.clientWidth, height: element.clientHeight }
      const rect = cardRect(cards)
      const readable = readableViewport(panel, rect)
      const view = whole ? readableViewport(panel, rect, 0) : readable
      setOverflow(readable.overflow)
      void flow.setViewport({ x: view.x, y: view.y, zoom: view.zoom }, duration ? { duration } : undefined)
    },
    [flow, cards],
  )

  // 효과에서 부르는 맞춤(최신 fitReadable): 효과는 배치·전체 화면·칸 크기가 바뀔 때만 돈다(함수가 새로 만들어질 때마다
  // 다시 맞추면 확대·이동·전체 보기 직후 맞춤 보기로 되돌아갈 수 있음)
  const refit = useEffectEvent((duration?: number) => fitReadable(duration))
  const resized = useEffectEvent(() => {
    if (!moved.current) fitReadable()
  })

  // 전체 화면에 들어가고 나올 때 칸 크기가 바뀐 뒤 한 번 다시 맞춘다(직접 옮긴 시점이어도)
  useEffect(() => {
    const timer = window.setTimeout(() => refit(200), 60)
    return () => window.clearTimeout(timer)
  }, [full])

  const nodes = useMemo<CardNode[]>(
    () => cardNodes(report, model, main, { selected, motion, focusMain, onExpand }),
    [report, model, selected, onExpand, main, motion, focusMain],
  )

  const edges = useMemo<Edge[]>(
    () => linkEdges(model, main, { selected, motion, focusMain, settled }),
    [model, selected, main, motion, focusMain, settled],
  )

  // 묶음을 펴고 접어 배치가 바뀌면 다시 맞춘다
  const first = useRef(true)
  useEffect(() => {
    moved.current = false
    refit(first.current ? undefined : 200)
    first.current = false
  }, [model])

  // 칸 경계를 끌어 크기가 바뀌어도(창 크기는 그대로) 맞춘다
  useEffect(() => {
    const element = box.current
    if (!element) return
    const resize = new ResizeObserver(() => resized())
    resize.observe(element)
    return () => resize.disconnect()
  }, [])

  // 초점만 옮긴다. 화면 밖 카드는 React Flow가 배율 그대로 옮겨 보여 준다(autoPanOnNodeFocus)
  const focusCard = (id: string) => {
    box.current?.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true })
  }

  // 펼친 직후에는 새 카드가 다음 그리기에서 붙으므로 몇 프레임 기다리며 찾는다
  useEffect(() => {
    if (!focusTarget) return
    let frame = 0
    let tries = 0
    const attempt = () => {
      const element = box.current?.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(focusTarget)}"]`)
      if (element || tries >= 30) {
        element?.focus({ preventScroll: true })
        onFocused?.()
        return
      }
      tries += 1
      frame = requestAnimationFrame(attempt)
    }
    attempt()
    return () => cancelAnimationFrame(frame)
  }, [focusTarget, model, onFocused])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const id = (event.target as HTMLElement).closest<HTMLElement>('.react-flow__node')?.dataset.id
    if (!id) return
    const direction = KEYS[event.key]
    if (direction) {
      event.preventDefault()
      const next = nearestInDirection(model.cards, id, direction)
      if (next) focusCard(next)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(id)
    } else if (event.key === 'Escape') {
      onSelect(null)
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 도구와 범례는 캔버스 밖 막대에 둔다(카드를 가리지 않게) */}
      <FlowToolbar
        mainLinks={main.links.size > 0}
        mainCards={main.cards.size > 0}
        motion={motion}
        onMotion={onMotion}
        focusMain={focusMain}
        onFocusMain={onFocusMain}
        onCollapseAll={onCollapseAll}
        onReplay={onReplay}
        onFit={() => {
          moved.current = false
          fitReadable(300)
        }}
        // 읽기 하한 없이 그래프 전체를 한눈에(글자는 작아짐). 그 뒤 칸 크기가 바뀌어도 이 시점을 지킨다
        onWhole={
          overflow
            ? () => {
                moved.current = true
                fitReadable(300, true)
              }
            : undefined
        }
        full={full}
        onToggleFull={onToggleFull}
      />
      <div ref={box} className="relative min-h-0 flex-1" onKeyDown={onKeyDown}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          ariaLabelConfig={ARIA}
          minZoom={0.2}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
          // 확대·이동 장치가 준비된 뒤 한 번 더 맞춘다(그 전에 맞춘 시점은 처음 시점으로 덮일 수 있음 — 다시 보기로 새로 그릴 때)
          onInit={() => {
            if (!moved.current) fitReadable()
          }}
          // 지도가 상세 스크롤 길 한가운데 있으므로 휠은 페이지를 내리고, 확대는 Ctrl+휠·두 손가락(전체 화면에서는 휠 그대로)
          preventScrolling={full}
          onNodeClick={(_, node) => onSelect(node.id)}
          onPaneClick={() => onSelect(null)}
          onMoveStart={(event) => {
            if (event) moved.current = true
          }}
          aria-label="설계변경 영향 지도"
        />
      </div>
    </div>
  )
}
