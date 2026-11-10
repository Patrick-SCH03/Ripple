// 추가손실 곡선 탭(DESIGN.md 6절): 계단 그래프(Recharts, 따로 불러옴) · 보류한 곡선 겹쳐 보기 · 계단 표(같은 내용).
// 겹쳐 보기는 표시 결과의 요청에 보류를 넣어 따로 분석한다(세션 초안은 바꾸지 않음).
import { LoaderCircle } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ApiError, api, type AnalysisResult, type CurvePoint, type HoldAdvice } from '@/api/client'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { InfoPop } from '@/components/common/InfoPop'
import { Button } from '@/components/ui/button'
import { formatDay } from '@/lib/format'
import { formatMoney, formatRange } from '@/lib/money'
import { curveSteps } from '@/lib/summary'

const LossCurve = lazy(() => import('@/components/curve/LossCurve'))

interface Held {
  poId: string
  label: string
  curve: CurvePoint[]
}

function Legend({ held }: { held: Held | null }) {
  return (
    <ul aria-hidden className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-foreground-secondary">
      <li className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 bg-primary" />
        추가손실(대표값)
      </li>
      <li className="flex items-center gap-1.5">
        <span className="h-2.5 w-4 bg-primary/15" />
        최소~최대
      </li>
      <li className="flex items-center gap-1.5">
        <span className="w-4 border-t-2 border-dashed border-danger" />
        결정 기한
      </li>
      {held && (
        <li className="flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed border-success" />
          {held.label}
        </li>
      )}
    </ul>
  )
}

export function CurveTab({ result }: { result: AnalysisResult }) {
  const { curve, deadline, holds } = result.timing
  const [held, setHeld] = useState<Held | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])

  const toggle = async (advice: HoldAdvice) => {
    controller.current?.abort()
    setFailure(null)
    if (held?.poId === advice.po_id) {
      setHeld(null)
      setLoading(null)
      return
    }
    const mine = new AbortController()
    controller.current = mine
    setLoading(advice.po_id)
    try {
      const request = {
        ...result.request,
        holds: [...result.request.holds, { po_id: advice.po_id, hold_days: advice.max_hold_days }],
      }
      const answer = await api.analyses(request, mine.signal)
      setHeld({
        poId: advice.po_id,
        label: `${advice.po_id} ${advice.max_hold_days}일 보류하면`,
        curve: answer.timing.curve,
      })
    } catch (caught) {
      if (mine.signal.aborted) return
      setFailure(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      if (controller.current === mine) setLoading(null)
    }
  }

  const steps = curveSteps(curve)
  return (
    <div className="space-y-3">
      {/* 곡선이 무엇인지(기간 · 기준일 확정 대비)는 늘 떠 있는 설명 줄 대신 오른쪽 'ⓘ 곡선 보는 법' */}
      <div className="flex flex-wrap items-center gap-2">
        {holds.map((advice) => {
          const on = held?.poId === advice.po_id
          return (
            <Button
              key={advice.po_id}
              size="sm"
              variant={on ? 'default' : 'outline'}
              aria-pressed={on}
              disabled={loading !== null && loading !== advice.po_id}
              onClick={() => void toggle(advice)}
            >
              {loading === advice.po_id && <LoaderCircle aria-hidden className="animate-spin" />}
              {advice.po_id} 보류한 곡선 겹쳐 보기
            </Button>
          )
        })}
        <InfoPop
          className="ml-auto"
          title="추가손실 곡선"
          label="곡선 보는 법"
          lines={[
            `기간 ${formatDay(curve[0].confirm_on)}~${formatDay(curve[curve.length - 1].confirm_on)}`,
            '그날 확정 시 기준일 확정 대비 추가손실 · 계단 = 비용이 바뀌는 날',
          ]}
        />
      </div>
      {failure && (
        <p role="alert" className="text-sm text-danger">
          보류한 곡선 계산 실패: {failure}
        </p>
      )}
      <ErrorBoundary fallback={<p className="text-sm">그래프 불러오기 실패 · 아래 표 참고</p>}>
        <Suspense fallback={<p className="flex h-72 items-center text-sm text-foreground-secondary">그래프를 불러오는 중…</p>}>
          <LossCurve curve={curve} deadline={deadline} held={held ?? undefined} />
        </Suspense>
      </ErrorBoundary>
      <Legend held={held} />
      {steps.length === 0 ? (
        <p className="text-sm">탐색 기간 안 확정을 미뤄도 비용 그대로</p>
      ) : (
        <table className="w-full text-sm">
          <caption className="mb-2 text-left text-md font-semibold">비용이 바뀌는 날</caption>
          <thead className="text-left text-foreground-secondary">
            <tr className="border-b border-border">
              <th className="py-1.5 font-medium">확정일</th>
              <th className="py-1.5 text-right font-medium">추가손실</th>
              <th className="py-1.5 pl-4 font-medium">이유</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => {
              const point = curve.find((p) => p.confirm_on === step.day)
              const loss = point?.additional_loss
              return (
                <tr key={step.day} className="border-b border-border align-top">
                  <td className="py-1.5 whitespace-nowrap">{formatDay(step.day)}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {formatMoney(step.added)}
                    {loss && loss.low !== loss.high && (
                      <span className="block text-foreground-secondary">{formatRange(loss.low, loss.high)}</span>
                    )}
                  </td>
                  <td className="py-1.5 pl-4">{step.events.join(', ') || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
