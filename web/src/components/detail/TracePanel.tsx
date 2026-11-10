// 연결 추적(docs/domain.md 13절): 대상 부재마다 도면(EBOM) → 블록(MBOM) → 발주 품목(구매) → 공정(시공).
// 고리는 지도 연결이라 이번 변경의 영향이 없어도 보이고, 영향이 걸린 고리만 굵게. 지도에 연결이 없으면 '끊김'으로 적는다.
// 영향 지도 아래에 접어 두고 펼치면 표. 결과에 없는 계산은 하지 않는다.
import { ChevronRight, Unlink } from 'lucide-react'
import { useState } from 'react'
import type { AnalysisResult, TraceChain, TraceLink } from '@/api/client'
import { TermInfo } from '@/components/common/TermInfo'
import { cn } from '@/lib/utils'

function Link({ link, onEvidence }: { link: TraceLink; onEvidence: (entityId: string) => void }) {
  const text = (
    <>
      {link.label}
      {link.status && <span className="text-foreground-secondary"> · {link.status}</span>}
    </>
  )
  return link.affected ? (
    <button
      type="button"
      className="text-left font-medium underline decoration-dotted underline-offset-2"
      onClick={() => onEvidence(link.entity_id)}
      title="영향 지도에서 근거 보기"
    >
      {text}
    </button>
  ) : (
    <span>{text}</span>
  )
}

function Cell({ links, onEvidence }: { links: readonly TraceLink[]; onEvidence: (entityId: string) => void }) {
  if (links.length === 0) return <span className="text-foreground-secondary">—</span>
  return (
    <ul className="space-y-0.5">
      {links.map((link) => (
        <li key={link.entity_id}>
          <Link link={link} onEvidence={onEvidence} />
        </li>
      ))}
    </ul>
  )
}

function Row({ chain, onEvidence }: { chain: TraceChain; onEvidence: (entityId: string) => void }) {
  const tag = chain.removed ? '빼는 부재' : null
  return (
    <tr className="border-b border-border align-top">
      <td className="py-1.5 pr-3">
        {chain.label}
        {tag && <span className="ml-1 text-sm text-foreground-secondary">({tag})</span>}
        {chain.gaps.length > 0 && (
          <p className="mt-0.5 flex items-start gap-1 text-sm text-warning">
            <Unlink aria-hidden className="mt-0.5 size-3 shrink-0" />
            {chain.gaps.join(' · ')}
          </p>
        )}
      </td>
      <td className="py-1.5 pr-3">
        <Cell links={chain.drawing ? [chain.drawing] : []} onEvidence={onEvidence} />
      </td>
      <td className="py-1.5 pr-3">
        <Cell links={chain.block ? [chain.block] : []} onEvidence={onEvidence} />
      </td>
      <td className="py-1.5 pr-3">
        <Cell links={chain.po_lines} onEvidence={onEvidence} />
      </td>
      <td className="py-1.5">
        <Cell links={chain.activities} onEvidence={onEvidence} />
      </td>
    </tr>
  )
}

export function TracePanel({ result, onEvidence }: { result: AnalysisResult; onEvidence: (entityId: string) => void }) {
  const [open, setOpen] = useState(false)
  const chains = result.trace
  if (chains === undefined || (chains !== null && chains.length === 0)) return null
  const gaps = chains?.reduce((n, chain) => n + (chain.gaps.length > 0 ? 1 : 0), 0) ?? 0
  return (
    // 영향 범위 카드 안 소구역(위 구분선 + 소제목, DetailSection SubSection과 같은 모양). 무엇을 잇는지·굵은 고리 뜻은 ⓘ
    <section aria-labelledby="trace-title" data-testid="trace-panel" className="border-t border-border pt-3">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
        >
          <h4 id="trace-title" className="flex items-center gap-1 text-md font-semibold">
            <ChevronRight aria-hidden className={cn('size-4 transition-transform', open && 'rotate-90')} />
            연결 추적
          </h4>
          {chains === null ? null : (
            <span className={cn('text-sm', gaps > 0 ? 'text-warning' : 'text-foreground-secondary')}>
              부재 {chains.length}개{gaps > 0 ? ` · 끊김 ${gaps}` : ''}
            </span>
          )}
        </button>
        <TermInfo term="trace" />
      </div>
      {open &&
        (chains === null ? (
          <p className="mt-2 text-sm text-foreground-secondary">연결 추적 정보 없음 · 다시 분석하면 표시</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-foreground-secondary">
                <tr className="border-b border-border">
                  <th className="py-1.5 pr-3 font-medium">대상 부재</th>
                  <th className="py-1.5 pr-3 font-medium">도면(설계 BOM)</th>
                  <th className="py-1.5 pr-3 font-medium">블록(생산 BOM)</th>
                  <th className="py-1.5 pr-3 font-medium">발주 품목(구매)</th>
                  <th className="py-1.5 font-medium">공정(시공)</th>
                </tr>
              </thead>
              <tbody>
                {chains.map((chain) => (
                  <Row key={chain.part_id} chain={chain} onEvidence={onEvidence} />
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  )
}
