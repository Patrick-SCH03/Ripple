// 결재·현황(팀장의 첫 화면, docs/records.md(기록·결재) 11절 · DESIGN.md 15절): 결재함 → 현황 → 성과 → 관리.
// 결정은 업무 화면에서 그 개정의 분석을 보며 한다(결재함 '열기' — 결정은 분석을 본 뒤에만).
// '인쇄·PDF'는 현황과 성과를 한 문서로 인쇄한다(주간 보고용). '엑셀로 내보내기'는 결재 대장(결재함 줄)·현황을 엑셀로.
import { LayoutGrid, Printer, RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { UserMenu } from '@/components/account/UserMenu'
import { BrandMark } from '@/components/common/BrandMark'
import { ExcelExportButton } from '@/components/common/ExcelExportButton'
import { ThemeMenu } from '@/components/shell/ThemeMenu'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { whoLabel } from '@/lib/account'
import { stampText } from '@/lib/manage'
import { APP_PATH } from '@/lib/route'
import { useTheme } from '@/lib/theme'
import { useLayoutMode } from '@/lib/viewport'
import { useSignedIn } from '@/state/sessionContext'
import { useManage } from '@/state/useManage'
import { navigate } from '@/state/useRoute'
import { AdminPanel } from './AdminPanel'
import { InboxPanel } from './InboxPanel'
import { PerformancePanel } from './PerformancePanel'
import { RecurringTypes } from './RecurringTypes'
import { StatusPanel } from './StatusPanel'

type Tab = 'inbox' | 'status' | 'performance' | 'admin'

/** 인쇄·PDF는 밝게(어둡게 토큰이면 흰 종이에 흰 글자): 인쇄 직전에 어둡게 클래스를 떼고 끝나면 되돌린다(Ctrl+P 포함). */
function usePrintLight() {
  useEffect(() => {
    const root = document.documentElement
    let wasDark = false
    const before = () => {
      wasDark = root.classList.contains('dark')
      root.classList.remove('dark')
    }
    const after = () => {
      if (wasDark) root.classList.add('dark')
    }
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])
}

export default function ManagePage() {
  const { me } = useSignedIn()
  const theme = useTheme()
  const mode = useLayoutMode()
  const manage = useManage()
  const [tab, setTab] = useState<Tab>('inbox')
  const { data } = manage
  usePrintLight()
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'inbox', label: '결재함', count: data?.inbox.length },
    { id: 'status', label: '현황' },
    { id: 'performance', label: '성과' },
    { id: 'admin', label: '관리' },
  ]
  return (
    <div className="min-h-dvh bg-canvas text-foreground" data-testid="manage">
      <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b border-border bg-surface px-3 print:hidden">
        <BrandMark size={22} className="shrink-0" />
        <span className="hidden text-md font-semibold tracking-tight sm:inline">Ripple</span>
        <nav aria-label="화면" className="ml-2 flex items-center gap-1">
          <span aria-current="page" className="rounded-sm bg-muted px-2.5 py-1 text-sm font-semibold whitespace-nowrap">
            결재·현황
          </span>
          <Button variant="ghost" size="sm" onClick={() => navigate(APP_PATH)} data-testid="to-workbench">
            <LayoutGrid aria-hidden />
            업무 화면
          </Button>
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <ThemeMenu theme={theme} health={null} />
          <UserMenu mode={mode} />
        </div>
      </header>
      {/* 상태 막대·칩 바탕색이 인쇄에서 빠지지 않게(물려받는 속성) */}
      <main className="mx-auto max-w-[1200px] px-4 py-5 [-webkit-print-color-adjust:exact] [print-color-adjust:exact] sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-headline font-semibold tracking-tight">결재·현황</h1>
            <p className="mt-1 text-sm text-foreground-secondary">
              {whoLabel(me)}
              {data && <> · {stampText(data.generated_at, [...data.inbox, ...data.proxy])}</>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            <Button variant="outline" onClick={manage.reload} disabled={manage.loading}>
              <RotateCw aria-hidden className={manage.loading ? 'animate-spin' : undefined} />
              새로 고침
            </Button>
            <Button variant="outline" onClick={() => window.print()} disabled={!data}>
              <Printer aria-hidden />
              인쇄·PDF
            </Button>
            {/* 결재 대장(결재함 줄)·현황을 엑셀로 — 숫자는 이 화면과 같은 결재·현황 계산 */}
            <ExcelExportButton
              load={() => api.exportManage(manage.days)}
              fallbackName="Ripple_결재대장.xlsx"
              disabled={!data}
              testId="manage-export"
            />
          </div>
        </div>
        {manage.error && (
          <p role="alert" className="mt-4 rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">
            {manage.error}
          </p>
        )}
        {!data ? (
          !manage.error && <p className="mt-10 text-center text-sm text-foreground-secondary">결재·현황을 불러오는 중…</p>
        ) : (
          <>
            <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} className="mt-4 gap-4 print:hidden">
              <TabsList variant="line" className="w-full justify-start border-b border-border">
                {tabs.map(({ id, label, count }) => (
                  <TabsTrigger
                    key={id}
                    value={id}
                    className="flex-none px-3 text-foreground-secondary data-active:text-foreground dark:text-foreground-secondary"
                  >
                    {label}
                    {count !== undefined && count > 0 && (
                      <span className="ml-1 rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular-nums">{count}</span>
                    )}
                  </TabsTrigger>
                ))}
              </TabsList>
              <TabsContent value="inbox">
                <InboxPanel items={data.inbox} proxy={data.proxy} now={data.generated_at} />
              </TabsContent>
              <TabsContent value="status" className="space-y-8">
                <StatusPanel data={data} />
                <RecurringTypes />
              </TabsContent>
              <TabsContent value="performance">
                <PerformancePanel data={data} days={manage.days} onDays={manage.setDays} loading={manage.loading} />
              </TabsContent>
              <TabsContent value="admin">
                <AdminPanel me={me} />
              </TabsContent>
            </Tabs>
            <div className="hidden space-y-8 print:block" data-testid="manage-print">
              <h2 className="text-lg font-semibold">현황</h2>
              <StatusPanel data={data} />
              <h2 className="text-lg font-semibold">
                성과 {data.performance.days == null ? '(전체 기간)' : `(최근 ${data.performance.days}일)`}
              </h2>
              <PerformancePanel data={data} days={data.performance.days ?? null} />
            </div>
          </>
        )}
      </main>
    </div>
  )
}
