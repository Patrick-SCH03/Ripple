// 반복 유형(합성 NCR, docs/records.md '합성 NCR'): 사전 점검 규칙과 같은 유형별 부적합 보고 건수의 작은 표(팀장 현황 탭).
// 실제 NCR 이력이 없어 합성 모드에서만 시연용 묶음이 있고, 늘 '합성 묶음(시연)'을 붙인다. 건수만(비율·금액 없음).
// 실데이터 모드면 서버가 available = false와 이유를 주고, 화면은 '아직 기록 없음'.
import { useEffect, useState } from 'react'
import { ApiError, api, type NcrSummary } from '@/api/client'

type Loaded = { kind: 'loading' } | { kind: 'failed'; message: string } | { kind: 'done'; summary: NcrSummary }

export function RecurringTypes() {
  const [state, setState] = useState<Loaded>({ kind: 'loading' })
  useEffect(() => {
    const controller = new AbortController()
    api.ncrSummary(controller.signal).then(
      (summary) => setState({ kind: 'done', summary }),
      (caught: unknown) => {
        if (controller.signal.aborted) return
        setState({ kind: 'failed', message: caught instanceof ApiError ? caught.message : '불러오기 실패' })
      },
    )
    return () => controller.abort()
  }, [])
  return (
    <section aria-labelledby="recurring-title" className="space-y-2" data-testid="recurring-types">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 id="recurring-title" className="text-md font-semibold">
          반복 유형(합성 NCR)
        </h3>
        {state.kind === 'done' && state.summary.available && (
          <span className="inline-flex h-6 items-center rounded-sm border border-border px-1.5 text-xs text-foreground-secondary">
            {state.summary.label}
          </span>
        )}
      </div>
      {state.kind === 'loading' && <p className="text-sm text-foreground-secondary">불러오는 중…</p>}
      {state.kind === 'failed' && <p className="text-sm text-danger">반복 유형 불러오기 실패 · {state.message}</p>}
      {state.kind === 'done' && !state.summary.available && (
        <p className="text-sm text-foreground-secondary">
          아직 기록 없음{state.summary.reason ? ` · ${state.summary.reason}` : ''}
        </p>
      )}
      {state.kind === 'done' && state.summary.available && (
        <>
          <table className="w-full max-w-md text-sm">
            <thead className="text-left text-foreground-secondary">
              <tr className="border-b border-border">
                <th className="py-1.5 font-medium">유형</th>
                <th className="py-1.5 text-right font-medium">건수</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {state.summary.counts.map((row) => (
                <tr key={row.ncr_type} className="border-b border-border">
                  <td className="py-1.5">{row.name}</td>
                  <td className="py-1.5 text-right">{row.count}건</td>
                </tr>
              ))}
              <tr className="font-medium">
                <td className="py-1.5">합계</td>
                <td className="py-1.5 text-right">{state.summary.total}건</td>
              </tr>
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}
