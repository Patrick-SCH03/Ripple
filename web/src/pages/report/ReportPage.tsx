// 설계변경 검토서 화면(DESIGN.md 14절 · docs/records.md(기록·결재) 9절): 기록된 개정 하나를 A4 세로 문서로 보이고, 위쪽
// '검토서 인쇄'로 브라우저 인쇄(PDF 저장)한다. 숫자는 모두 그 기록 본문의 분석 결과(lib/report.ts · sheet.ts).
// 이 화면에 있는 동안은 밝게(흰 종이) — 나갈 때 원래 밝기로 되돌린다. 본문은 Report.tsx, 불러오기는 useReport.ts.
import { ArrowLeft, Printer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { BrandMark } from '@/components/common/BrandMark'
import { Button } from '@/components/ui/button'
import { useLightOnly } from '@/lib/theme'
import { navigate } from '@/state/useRoute'
import { Report } from './Report'
import { SHEET_TITLE, kstStamp } from './sheet'
import { useReport } from './useReport'
import './report.css'

export default function ReportPage({ ecnId, revision }: { ecnId: string; revision: number }) {
  const loaded = useReport(ecnId, revision)
  const [issuedAt] = useState(() => kstStamp(new Date().toISOString()))

  // 인쇄는 밝게: 떠 있는 동안 밝게, 나갈 때 고른 밝기로(소개 화면과 같은 한 곳 — 뒤로 가기로 소개에 가도 순서가 꼬이지 않게)
  useLightOnly()

  useEffect(() => {
    // 문서 제목 = PDF 저장 기본 파일 이름
    if (loaded?.kind === 'ok') document.title = `${SHEET_TITLE}_${loaded.model.ecnId}_개정${loaded.model.revision}`
  }, [loaded])

  return (
    <div className="report-page min-h-screen bg-canvas text-foreground" data-testid="report-page">
      <div className="report-toolbar sticky top-0 z-10 border-b border-border bg-surface/95 px-4 py-2">
        <div className="mx-auto flex max-w-[210mm] flex-wrap items-center gap-2">
          <BrandMark size={26} className="shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block font-semibold tracking-tight">{SHEET_TITLE}</span>
            <span className="hidden text-xs text-foreground-secondary sm:block">A4 세로 · 인쇄 창에서 'PDF로 저장' 가능</span>
          </span>
          <Button variant="outline" size="sm" onClick={() => navigate('/app')}>
            <ArrowLeft aria-hidden />
            업무 화면으로
          </Button>
          <Button size="sm" onClick={() => window.print()} disabled={loaded?.kind !== 'ok'} data-testid="report-print">
            <Printer aria-hidden />
            검토서 인쇄
          </Button>
        </div>
      </div>
      <div className="px-4 py-6">
        <article className="report-sheet rp-fixed-type mx-auto bg-surface text-sm leading-normal" data-testid="report-sheet">
          {loaded === null ? (
            <p className="text-foreground-secondary">검토서 만드는 중…</p>
          ) : loaded.kind === 'ok' ? (
            <Report model={loaded.model} sheet={loaded.sheet} issuedAt={issuedAt} />
          ) : (
            <p role="alert" className="text-danger" data-testid="report-missing">
              {loaded.kind === 'missing'
                ? '없는 기록 · 설계변경 번호·개정 번호 확인'
                : loaded.kind === 'mismatch'
                  ? '이 개정의 기록 읽기 실패 · 감사 로그 확인 필요'
                  : loaded.message}
            </p>
          )}
        </article>
      </div>
    </div>
  )
}
