// 근거 패널: 요약(영향 수·종류·확인 필요)과, 노드를 고르면 그 엔터티의 영향·근거 경로, 묶음을 고르면 구성원 목록.
// 규칙 ID·분석 ID·버전은 첫 화면에 쓰지 않고 펼침 안에 둔다(DESIGN.md 2절).
import type { KeyboardEvent } from 'react'
import type { GraphNode, Impact, ImpactView } from '@/api/client'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import { Button } from '@/components/ui/button'
import { cardText, type GraphCard } from '@/lib/graphCards'
import {
  ATTR_NAMES,
  ENTITY_NAMES,
  IMPACT_NAMES,
  RELATION_NAMES,
  ROLE_NAMES,
  RULE_TITLES,
  UNRESOLVED_NAMES,
  attrValue,
  nameOf,
} from '@/lib/labels'
import { groupNotes, type NoteItem } from '@/lib/resultNotes'
import { impactsByEntity, roleOf, summarize, topSeverity } from '@/lib/ripple'

interface Props {
  report: ImpactView
  selected: string | null
  onSelect: (id: string | null) => void
  /** 그래프의 묶음 카드(넓은 화면). 고른 ID가 묶음이면 구성원 목록을 보인다. */
  groups?: ReadonlyMap<string, GraphCard>
  onExpand?: (groupId: string) => void
  /** 요약의 '영향 목록'을 그릴까(좁은 화면은 바로 위 들여쓴 목록이 같은 엔터티를 이미 보여 빼요). 기본 true. */
  list?: boolean
}

/** 근거 세부에서 Esc = 전체 요약으로(초점은 고르기 전 자리로 돌아간다). */
const backOnEscape = (onBack: () => void) => (event: KeyboardEvent<HTMLDivElement>) => {
  if (event.key === 'Escape') onBack()
}

export function EvidencePanel({ report, selected, onSelect, groups, onExpand, list = true }: Props) {
  const nodes = new Map(report.graph.nodes.map((n) => [n.id, n]))
  const label = (id: string) => nodes.get(id)?.label ?? id
  const node = selected ? nodes.get(selected) : undefined
  if (node) return <NodeDetail node={node} report={report} label={label} onBack={() => onSelect(null)} />
  const group = selected ? groups?.get(selected) : undefined
  if (group) {
    return (
      <GroupDetail group={group} report={report} label={label} onSelect={onSelect} onExpand={onExpand} />
    )
  }

  const summary = summarize(report)
  // 결과 안내: 사람이 확인할 것은 '확인 필요' 카드에, 모르는 문장은 아래 참고로(늘 붙는 가정·한계는 화면에 내지 않음, lib/resultNotes)
  const notes = groupNotes(report.notes)
  return (
    <div className="evidence">
      <section className="headline">
        <p className="eyebrow">영향</p>
        <p className="big-number">
          {summary.total}
          <span>건</span>
        </p>
        {/* 보조 한 줄: 결정에 쓰는 높은 심각도만(엔터티 수는 영향 목록·지도가 보임) */}
        {summary.high > 0 && <p className="sub">심각도 높음 {summary.high}건</p>}
      </section>
      <section className="chips" aria-label="영향 종류">
        {summary.byType.map(([type, count]) => (
          <span key={type} className="chip">
            {IMPACT_NAMES[type]} <b>{count}</b>
          </span>
        ))}
      </section>
      {(report.unresolved.length > 0 || notes.check.length > 0) && (
        <section className="card warn" data-testid="evidence-check">
          <h3>확인 필요</h3>
          <ul>
            {report.unresolved.map((item) => (
              <li key={`${item.kind}-${item.entity_id ?? ''}`}>
                <button type="button" className="link" onClick={() => item.entity_id && onSelect(item.entity_id)}>
                  {nameOf(UNRESOLVED_NAMES, item.kind)} · {item.entity_id ? label(item.entity_id) : '전체'}
                </button>
                <p>{item.reason}</p>
              </li>
            ))}
            {notes.check.map((item, i) => (
              <li key={`note-${i}`}>
                <p className="font-semibold text-foreground">{item.label}</p>
                <p>{item.text}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {list && (
        <section className="card">
          <h3>영향 목록</h3>
          <ul className="impact-list">
            {report.impacts.map((impact) => (
              <li key={`${impact.entity_id}-${impact.rule_id}-${impact.impact_type}`}>
                <button
                  type="button"
                  className="impact-row"
                  data-entity-row={impact.entity_id}
                  onClick={() => onSelect(impact.entity_id)}
                >
                  <SeverityBadge severity={impact.severity} />
                  <span className="impact-name">{IMPACT_NAMES[impact.impact_type]}</span>
                  <span className="impact-entity">{label(impact.entity_id)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Notes other={notes.other} />
    </div>
  )
}

function NodeDetail({ node, report, label, onBack }: { node: GraphNode; report: ImpactView; label: (id: string) => string; onBack: () => void }) {
  const impacts = impactsByEntity(report).get(node.id) ?? []
  const role = roleOf(node)
  const attrs = Object.entries(node.attrs ?? {}).filter(([key, value]) => key !== 'role' && value !== null && value !== '')
  return (
    <div className="evidence" onKeyDown={backOnEscape(onBack)}>
      <button type="button" className="back" onClick={onBack}>
        ← 전체 요약
      </button>
      <section className="headline">
        <p className="eyebrow">
          {nameOf(ENTITY_NAMES, node.type)}
          {role && ` · ${nameOf(ROLE_NAMES, role)}`}
          {node.virtual && ' · 변경으로 생김'}
        </p>
        <h2 className="node-title" tabIndex={-1} data-evidence-title>
          {node.label}
        </h2>
        <p className="sub mono">{node.id}</p>
      </section>
      {attrs.length > 0 && (
        <dl className="attrs">
          {attrs.map(([key, value]) => (
            <div key={key}>
              <dt>{nameOf(ATTR_NAMES, key)}</dt>
              <dd>{attrValue(key, value as string | number | boolean)}</dd>
            </div>
          ))}
        </dl>
      )}
      {impacts.length === 0 ? (
        <p className="empty">{role ? '이번 변경의 출발점' : '이 엔터티에 직접 난 영향 없음'}</p>
      ) : (
        impacts.map((impact) => <ImpactCard key={`${impact.rule_id}-${impact.impact_type}`} impact={impact} label={label} />)
      )}
    </div>
  )
}

function GroupDetail({
  group,
  report,
  label,
  onSelect,
  onExpand,
}: {
  group: GraphCard
  report: ImpactView
  label: (id: string) => string
  onSelect: (id: string | null) => void
  onExpand?: (groupId: string) => void
}) {
  const byEntity = impactsByEntity(report)
  const { title } = cardText(report, group)
  const onBack = () => onSelect(null)
  return (
    <div className="evidence" onKeyDown={backOnEscape(onBack)}>
      <button type="button" className="back" onClick={onBack}>
        ← 전체 요약
      </button>
      <section className="headline">
        <p className="eyebrow">묶음 · {group.members.length}개</p>
        <h2 className="node-title" tabIndex={-1} data-evidence-title>
          {title}
        </h2>
      </section>
      {onExpand && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => onExpand(group.id)}>
          그래프에서 펼치기
        </Button>
      )}
      <ul className="impact-list" aria-label="묶음 구성원">
        {group.members.map((id) => {
          const impacts = byEntity.get(id) ?? []
          const top = topSeverity(impacts)
          return (
            <li key={id}>
              <button type="button" className="impact-row" data-entity-row={id} onClick={() => onSelect(id)}>
                {top ? <SeverityBadge severity={top} /> : <span />}
                <span className="impact-name">{label(id)}</span>
                <span className="impact-entity">
                  {[...new Set(impacts.map((i) => nameOf(IMPACT_NAMES, i.impact_type)))].join(' · ') || '영향 없음'}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function ImpactCard({ impact, label }: { impact: Impact; label: (id: string) => string }) {
  return (
    <article className="card">
      <header className="card-head">
        <SeverityBadge severity={impact.severity} />
        <h3>{IMPACT_NAMES[impact.impact_type]}</h3>
      </header>
      {RULE_TITLES[impact.rule_id] && <p className="rule-line">{RULE_TITLES[impact.rule_id]}</p>}
      {impact.note && <p className="note">{impact.note}</p>}
      {impact.path.length > 0 && (
        <ol className="path" aria-label="근거 경로">
          <li>{label(impact.path[0].src)}</li>
          {impact.path.map((hop) => (
            <li key={`${hop.src}-${hop.dst}-${hop.rule_id}`}>
              <span className="hop">{nameOf(RELATION_NAMES, hop.relation)}</span>
              {label(hop.dst)}
            </li>
          ))}
        </ol>
      )}
      <details className="details mt-2">
        <summary>규칙</summary>
        <p className="mono">
          {[impact.rule_id, ...impact.path.map((hop) => hop.rule_id)].filter((id, i, all) => all.indexOf(id) === i).join(' · ')}
        </p>
      </details>
    </article>
  )
}

/**
 * 결과 안내의 나머지: 모르는 문장(참고, 그대로). 늘 붙는 계산 가정·한계와 분석 ID·지도·규칙표 판은 업무 화면에서 뺐다
 * (실무 판단에 쓰지 않는 개발용 정보 — 계산 가정은 사용 안내·엔진 명세, 분석 ID는 기록·검토서에 남는다).
 */
function Notes({ other }: { other: NoteItem[] }) {
  if (other.length === 0) return null
  return (
    <section className="grid gap-2 text-sm text-foreground-secondary" aria-label="결과 안내">
      {other.map((item, i) => (
        <p key={`other-${i}`}>
          <strong className="font-semibold text-foreground">{item.label}</strong> {item.text}
        </p>
      ))}
    </section>
  )
}
