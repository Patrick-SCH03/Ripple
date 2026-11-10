// 검토서 불러오기: 설계변경의 개정 목록에서 그 개정의 기록을 찾아 리포트 모델(lib/report.ts)과 검토서 전용 값(sheet.ts)으로
// 만든다. 둘 다 같은 기록 본문·감사 줄에서 온다(지금 다시 계산하지 않음).
import { useEffect, useState } from 'react'
import { ApiError, api } from '@/api/client'
import { reportOf, type ReportModel } from '@/lib/report'
import { sheetOf, type SheetModel } from './sheet'

type Loaded =
  | { kind: 'ok'; model: ReportModel; sheet: SheetModel }
  | { kind: 'missing' }
  | { kind: 'mismatch' }
  | { kind: 'error'; message: string }

/** 불러오는 중이면 null. 없는 개정·기록은 missing, 기록 본문이 개정과 맞지 않으면 mismatch. */
export function useReport(ecnId: string, revision: number): Loaded | null {
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const detail = await api.ecn(ecnId)
        const summary = detail.revisions.find((r) => r.revision === revision)
        if (!summary) {
          if (live) setLoaded({ kind: 'missing' })
          return
        }
        const record = await api.record(summary.record_id)
        const model = reportOf(detail, record, revision)
        if (!live) return
        if (model === 'no_revision') setLoaded({ kind: 'missing' })
        else if (model === 'record_mismatch') setLoaded({ kind: 'mismatch' })
        else {
          const sheet = sheetOf(record.body.result, detail.audit, revision, summary.recorded_at)
          setLoaded({ kind: 'ok', model, sheet })
        }
      } catch (caught) {
        if (!live) return
        if (caught instanceof ApiError && caught.status === 404) setLoaded({ kind: 'missing' })
        else setLoaded({ kind: 'error', message: caught instanceof ApiError ? caught.message : String(caught) })
      }
    }
    void load()
    return () => {
      live = false
    }
  }, [ecnId, revision])

  return loaded
}
