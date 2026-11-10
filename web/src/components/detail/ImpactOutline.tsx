// 들여쓴 영향 목록: 좁은 화면(태블릿·휴대전화)에서 영향 지도 그래프 대신 쓴다(DESIGN.md 7절). 줄을 누르면 근거.
// 지도가 상세 위쪽(할 일 위)에 있으므로 처음 8줄만 보이고 나머지는 '더 보기'로 편다 — 고른 줄이 접힌 쪽이면 편다.
import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ImpactView } from '@/api/client'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import { ENTITY_NAMES, RELATION_NAMES, ROLE_NAMES, nameOf } from '@/lib/labels'
import { impactsByEntity, outlineOf, roleOf, topSeverity } from '@/lib/ripple'

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
}

/** 접었을 때 보이는 줄 수. 두 줄 남짓만 더 있으면 접지 않는다(단추가 줄보다 크지 않게). */
const FIRST = 8

export function ImpactOutline({ report, selected, onSelect }: Props) {
  const rows = useMemo(() => outlineOf(report), [report])
  const nodes = useMemo(() => new Map(report.graph.nodes.map((node) => [node.id, node])), [report])
  const byEntity = useMemo(() => impactsByEntity(report), [report])
  const [opened, setOpened] = useState(() => rows.findIndex((row) => row.id === selected) >= FIRST)
  // 접힌 쪽 줄을 다른 곳(팔레트·비용 줄)에서 고르면 그 순간 편다(렌더 중 상태 맞추기 — 다시 접을 수는 있게)
  const [seen, setSeen] = useState(selected)
  if (selected !== seen) {
    setSeen(selected)
    if (rows.findIndex((row) => row.id === selected) >= FIRST) setOpened(true)
  }
  const foldable = rows.length > FIRST + 2
  const open = !foldable || opened
  const shown = open ? rows : rows.slice(0, FIRST)
  return (
    <section aria-labelledby="impact-outline-title" className="px-2 py-3">
      <h3 id="impact-outline-title" className="px-2 pb-1 text-sm font-semibold text-foreground-secondary">
        변경 지점부터 영향이 이어지는 순서
      </h3>
      <ul id="impact-outline-rows">
        {shown.map((row) => {
          const node = nodes.get(row.id)
          if (!node) return null
          const role = roleOf(node)
          const severity = topSeverity(byEntity.get(row.id))
          const how = [
            nameOf(ENTITY_NAMES, node.type),
            role ? nameOf(ROLE_NAMES, role) : null,
            row.relation ? `${nameOf(RELATION_NAMES, row.relation)}${row.virtual ? '(변경으로 생김)' : ''}` : null,
          ].filter(Boolean)
          return (
            <li key={row.id}>
              <button
                type="button"
                aria-current={selected === row.id ? 'true' : undefined}
                data-entity-row={row.id}
                onClick={() => onSelect(row.id)}
                className="relative flex min-h-11 w-full items-center gap-2 rounded-sm py-1.5 pr-2 text-left hover:bg-hover aria-[current=true]:bg-muted"
                style={{ paddingLeft: 8 + row.depth * 16 }}
              >
                {row.depth > 0 && (
                  <span aria-hidden className="text-muted-foreground">
                    └
                  </span>
                )}
                <span className="sr-only">{row.depth}단계,</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base">{node.label}</span>
                  <span className="block text-xs text-foreground-secondary">{how.join(' · ')}</span>
                </span>
                {severity && <SeverityBadge severity={severity} />}
              </button>
            </li>
          )
        })}
      </ul>
      {foldable && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls="impact-outline-rows"
          onClick={() => setOpened((now) => !now)}
          className="mt-1 flex min-h-11 items-center gap-1 rounded-sm px-2 text-sm font-medium text-primary hover:bg-hover"
          data-testid="impact-outline-more"
        >
          {open ? '접기' : `영향 ${rows.length - FIRST}곳 더 보기`}
          <ChevronDown aria-hidden className={open ? 'size-4 rotate-180' : 'size-4'} />
        </button>
      )}
    </section>
  )
}
