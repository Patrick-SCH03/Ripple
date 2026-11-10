// 관리(팀장): 관리 일(구성원 · 감사 로그 · AI 호출 기록 · 지도·엑셀)을 한곳에.
// 대화상자는 위 막대 사용자 메뉴와 같은 것을 쓴다.
import { Bot, FileSpreadsheet, ShieldCheck, Users, type LucideIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Me } from '@/api/client'
import { AuditDialog } from '@/components/account/AuditDialog'
import { LlmCallsDialog } from '@/components/account/LlmCallsDialog'
import { MembersDialog } from '@/components/account/MembersDialog'
import { Button } from '@/components/ui/button'
import { can } from '@/lib/account'
import { APP_PATH } from '@/lib/route'
import { navigate } from '@/state/useRoute'

type Open = 'members' | 'audit' | 'llm' | null

export function AdminPanel({ me }: { me: Me }) {
  const [open, setOpen] = useState<Open>(null)
  return (
    <section aria-label="관리" className="space-y-6" data-testid="admin-panel">
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr))]">
        {can(me, 'manage_accounts') && (
          <Card icon={Users} title="구성원 관리" body="계정 추가, 역할(담당자·팀장·파트장·본부장), 비밀번호 초기화, 사용 중지">
            <Button variant="outline" onClick={() => setOpen('members')} data-testid="admin-members">
              구성원 관리 열기
            </Button>
          </Card>
        )}
        {can(me, 'approve') && (
          <Card icon={ShieldCheck} title="감사 로그 확인" body="기록·결재 이력 변조 여부를 해시 사슬로 확인">
            <Button variant="outline" onClick={() => setOpen('audit')}>
              감사 로그 확인
            </Button>
          </Card>
        )}
        {can(me, 'manage_accounts') && (
          <Card icon={Bot} title="AI 호출 기록" body="외부 AI를 언제·어떤 작업에 호출했는지(내용 없이 시각·작업·결과만)">
            <Button variant="outline" onClick={() => setOpen('llm')}>
              AI 호출 기록 보기
            </Button>
          </Card>
        )}
        {can(me, 'import') && (
          <Card icon={FileSpreadsheet} title="지도·엑셀 가져오기" body="BOM·발주대장·공정표 엑셀로 지도 교체 · 업무 화면 위 막대의 지도 메뉴">
            <Button variant="outline" onClick={() => navigate(APP_PATH)}>
              업무 화면으로
            </Button>
          </Card>
        )}
      </div>
      <MembersDialog open={open === 'members'} onOpenChange={(next) => !next && setOpen(null)} />
      <AuditDialog open={open === 'audit'} onOpenChange={(next) => !next && setOpen(null)} />
      <LlmCallsDialog open={open === 'llm'} onOpenChange={(next) => !next && setOpen(null)} />
    </section>
  )
}

function Card({ icon: Icon, title, body, children }: { icon: LucideIcon; title: string; body: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-primary" />
        <div>
          <p className="text-md font-semibold">{title}</p>
          <p className="mt-1 text-sm text-foreground-secondary">{body}</p>
        </div>
      </div>
      <div className="mt-auto">{children}</div>
    </div>
  )
}
