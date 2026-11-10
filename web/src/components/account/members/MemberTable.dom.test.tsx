// @vitest-environment jsdom
// 구성원 표의 삭제(DOM): 줄마다 '삭제' → 그 줄에서 한 번 더 묻기(무엇이 사라지는지 한 줄 · 왼쪽 닫기 · 오른쪽 위험 색 삭제),
// 지울 수 없는 줄(나·고정 계정·마지막 팀장)은 단추 대신 이유.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Account } from '@/api/client'
import { MemberTable } from './MemberTable'
import type { Confirming, MemberRows } from './useMembers'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const mounted: Root[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  document.body.innerHTML = ''
})

const at = '2026-10-20T01:02:03+00:00'
const account = (login_id: string, name: string, role: Account['role'] = 'member', disabled = false): Account => ({
  login_id,
  name,
  role,
  disabled,
  must_change_password: false,
  created_at: at,
  last_login_at: at,
})

const LEAD = account('lead', '팀장', 'admin')
const KIM = account('kim', '김담당')
const QUICK = account('quick-lead', '박팀장', 'admin')

function rows(accounts: Account[], extra: Partial<MemberRows> = {}): MemberRows {
  return {
    accounts,
    busy: null,
    confirming: null,
    onConfirming: vi.fn(),
    onReset: vi.fn(),
    onUpdate: vi.fn(),
    onDelete: vi.fn(),
    ...extra,
  }
}

async function mount(meId: string, value: MemberRows) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  mounted.push(root)
  await act(async () => root.render(<MemberTable meId={meId} rows={value} />))
  const row = (id: string) => container.querySelector<HTMLElement>(`[role="row"][data-login="${id}"]`)!
  const buttons = (id: string) => Array.from(row(id).querySelectorAll('button'))
  return { row, buttons, texts: (id: string) => buttons(id).map((b) => b.textContent?.trim()) }
}

describe('구성원 표 — 삭제', () => {
  it("바꿀 수 있는 줄에 '삭제', 누르면 그 줄의 삭제 확인을 연다", async () => {
    const value = rows([LEAD, KIM, QUICK])
    const { buttons, texts } = await mount('lead', value)
    expect(texts('kim')).toEqual(['비밀번호 초기화', '사용 중지', '삭제'])
    const remove = buttons('kim').find((b) => b.textContent?.includes('삭제'))!
    expect(remove.getAttribute('aria-label')).toBe('김담당 계정 삭제')
    await act(async () => remove.click())
    expect(value.onConfirming).toHaveBeenCalledWith({ loginId: 'kim', action: 'delete' } satisfies Confirming)
    expect(value.onDelete).not.toHaveBeenCalled()
  })

  it('확인 줄: 무엇이 사라지는지(기록의 이름은 남음) · 왼쪽 닫기 · 오른쪽 위험 색 삭제, 누르면 그 계정을 지움', async () => {
    const value = rows([LEAD, KIM], { confirming: { loginId: 'kim', action: 'delete' } })
    const { row, buttons, texts } = await mount('lead', value)
    const line = row('kim').querySelector('[data-testid="member-delete-confirm"]')!
    expect(line.textContent).toContain('계정·로그인 삭제')
    expect(line.textContent).toContain('기록·결재에 남은 이름은 그대로')
    expect(texts('kim')).toEqual(['닫기', '삭제'])
    const [close, confirm] = buttons('kim')
    expect(close.dataset.variant).toBe('outline')
    expect(confirm.dataset.variant).toBe('destructive')
    await act(async () => confirm.click())
    expect(value.onDelete).toHaveBeenCalledWith(KIM)
    await act(async () => close.click())
    expect(value.onConfirming).toHaveBeenCalledWith(null)
  })

  it('비밀번호 초기화 확인은 그대로(기본 색 초기화), 다른 줄의 확인은 이 줄에 영향 없음', async () => {
    const other = account('lee', '이담당')
    const value = rows([LEAD, KIM, other], { confirming: { loginId: 'kim', action: 'reset' } })
    const { buttons, texts, row } = await mount('lead', value)
    expect(texts('kim')).toEqual(['닫기', '초기화'])
    expect(buttons('kim')[1].dataset.variant).toBe('default')
    expect(row('kim').textContent).toContain('새 임시 비밀번호 발급')
    expect(texts('lee')).toEqual(['비밀번호 초기화', '사용 중지', '삭제'])
  })

  it('진행 중이면 삭제·확인 단추가 막힘', async () => {
    const value = rows([LEAD, KIM], { busy: 'update:lead' })
    const { buttons } = await mount('lead', value)
    expect(buttons('kim').every((b) => b.disabled)).toBe(true)
    const confirming = rows([LEAD, KIM], { busy: 'delete:kim', confirming: { loginId: 'kim', action: 'delete' } })
    document.body.innerHTML = ''
    const second = await mount('lead', confirming)
    expect(second.buttons('kim')[1].disabled).toBe(true)
  })

  it('지울 수 없는 줄은 단추 대신 이유: 나 · 고정 계정(자물쇠 줄) · 마지막 팀장', async () => {
    const value = rows([LEAD, KIM, QUICK])
    const { row, texts } = await mount('lead', value)
    expect(texts('lead')).toEqual([])
    expect(row('lead').querySelector('[data-testid="member-undeletable"]')?.textContent).toBe('내 계정 삭제 불가')
    expect(texts('quick-lead')).toEqual([])
    expect(row('quick-lead').querySelector('[data-testid="member-locked"]')).not.toBeNull()
    expect(row('quick-lead').querySelector('[data-testid="member-undeletable"]')).toBeNull()

    document.body.innerHTML = ''
    const dev = await mount('dev', rows([LEAD, KIM])) // 개발 모드: 사용 중인 팀장이 lead 하나
    expect(dev.texts('lead')).toEqual(['비밀번호 초기화', '사용 중지'])
    expect(dev.row('lead').querySelector('[data-testid="member-undeletable"]')?.textContent).toBe(
      '마지막 팀장 · 삭제 불가',
    )
    expect(dev.texts('kim')).toContain('삭제')
  })
})
