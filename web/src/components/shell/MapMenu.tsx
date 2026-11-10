// 지도 메뉴(위 막대): 지금 쓰는 지도 이름과 데이터 종류, 누르면 지도 목록(전환) · 엑셀 가져오기 · 이 지도 엑셀로 내려받기.
// 실제 데이터 지도(엑셀로 가져온 지도)는 AI 외부 호출을 하지 않는다는 것을 데이터 종류 옆에 함께 보인다.
// 전환·가져오기는 관리자만(서버도 403으로 막음): 다른 역할은 지금 지도와 안내 한 줄만 보인다.
// 상태 올리기(바뀌는 시트만)는 기록 권한(담당자 이상)이면 누구나.
import { Check, Database, FileDown, FileUp, Lock, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, type SnapshotInfo } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { can } from '@/lib/account'
import { cn } from '@/lib/utils'
import type { LayoutMode } from '@/lib/viewport'
import { formatDay } from '@/lib/format'
import { freshnessLines, mapDetail } from '@/lib/workspace'
import { useSignedIn } from '@/state/sessionContext'
import type { ImportMode } from '@/components/workspace/ImportDialog'
import type { WorkspaceState } from '@/state/useWorkspace'

interface Props {
  mode: LayoutMode
  workspace: WorkspaceState
  onImport: (mode?: ImportMode) => void
}

export function MapMenu({ mode, workspace, onImport }: Props) {
  const { me } = useSignedIn()
  const { list, active, switching } = workspace
  const canSwitch = can(me, 'switch_map')
  const canImport = can(me, 'import')
  if (!list || !active) return null
  const real = list.data_mode === 'real'
  const kind = real ? '실제 데이터' : '합성 데이터'
  const compact = mode === 'phone'
  const fresh = list.freshness ? freshnessLines(list.freshness) : null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          aria-label={`지도: ${active.name} · ${kind}${real ? ' · AI 외부 호출 꺼짐' : ''}`}
          // 1024~1439px는 큰 글자라 지도 이름 칸을 줄여(말줄임, 전체는 메뉴 안) 위 막대가 넘치지 않게
          className={cn('max-w-72 min-w-0', mode === 'desktop' && 'max-w-56')}
          disabled={switching}
        >
          <Database aria-hidden />
          {!compact && <span className="min-w-0 truncate">{active.name}</span>}
          {!compact && (
            <span
              data-testid="data-kind"
              className={
                real
                  ? 'shrink-0 rounded-sm border border-warning/50 px-1 text-xs text-warning'
                  : 'shrink-0 rounded-sm border border-border px-1 text-xs text-foreground-secondary'
              }
            >
              {kind}
            </span>
          )}
          {fresh?.stale && (
            <span
              data-testid="stale-badge"
              aria-label="7일 이상 미확인 발주 있음"
              className="size-2 shrink-0 rounded-full bg-warning"
            />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>지도</DropdownMenuLabel>
        {(canSwitch ? list.items : [active]).map((item) => (
          <MapItem
            key={item.snapshot_id}
            item={item}
            current={item.snapshot_id === list.active_snapshot_id}
            onChoose={() => void workspace.activate(item.snapshot_id)}
          />
        ))}
        {!canSwitch && (
          <p className="flex gap-2 px-2 py-1.5 text-xs text-foreground-secondary" data-testid="map-locked">
            <Lock aria-hidden className="mt-px size-3.5 shrink-0" />
            지도 전환·엑셀 전체 가져오기는 팀장만 · 발주·공정 상태는 '상태 올리기'로
          </p>
        )}
        {fresh && list.freshness && (
          <div className="px-2 py-1.5 text-xs" data-testid="freshness">
            <p className="font-semibold text-foreground-secondary">
              자료 날짜(오늘 {formatDay(list.freshness.today)} 기준)
            </p>
            {fresh.lines.map((line) => (
              <p key={line} className={fresh.stale && line.startsWith('발주') ? 'text-warning' : 'text-foreground-secondary'}>
                {line}
              </p>
            ))}
            {fresh.stale && (
              <p className="text-foreground-secondary">
                확인: 분석 화면 '현장 상태 확인' 또는 상태 올리기
              </p>
            )}
          </div>
        )}
        <DropdownMenuSeparator />
        {canImport && (
          <DropdownMenuItem onSelect={() => onImport('full')}>
            <FileUp aria-hidden />
            엑셀 가져오기…
          </DropdownMenuItem>
        )}
        {can(me, 'record') && (
          <DropdownMenuItem onSelect={() => onImport('status')} data-testid="status-upload">
            <RefreshCw aria-hidden />
            상태 올리기(발주·공정)…
          </DropdownMenuItem>
        )}
        {can(me, 'export') && (
          <DropdownMenuItem asChild>
            <a href={api.exportUrl(active.snapshot_id)} download>
              <FileDown aria-hidden />이 지도 엑셀로 내려받기
            </a>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <p className="flex gap-2 px-2 py-1.5 text-xs text-foreground-secondary">
          <ShieldCheck aria-hidden className="mt-px size-3.5 shrink-0" />
          {real
            ? '실제 데이터 지도 · AI 외부 호출 없음(문장 해석·설명은 서버 규칙으로만)'
            : list.llm_external
              ? '합성 데이터 지도 · AI 외부 호출 사용(해석 보조·설명 고르기)'
              : '합성 데이터 지도 · AI 외부 호출 설정 없음'}
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function MapItem({ item, current, onChoose }: { item: SnapshotInfo; current: boolean; onChoose: () => void }) {
  return (
    <DropdownMenuItem
      onSelect={current ? undefined : onChoose}
      aria-current={current ? 'true' : undefined}
      className="items-start"
    >
      <Check aria-hidden className={current ? 'mt-0.5' : 'invisible mt-0.5'} />
      <span className="min-w-0">
        <span className="block truncate">{item.name}</span>
        <span className="block text-xs text-foreground-secondary">{mapDetail(item)}</span>
      </span>
    </DropdownMenuItem>
  )
}
