import { describe, expect, it } from 'vitest'
import type { EmailDraft, RenderedText } from '@/api/client'
import { URL_LIMIT, bodyText, composeUrl, fullText, nextToOpen, planCompose, recipientLine } from './mail'

const paragraph = (...lines: string[]): RenderedText => ({
  source: 'template',
  blocks: lines.map((text) => ({ kind: 'text', text, template_id: 'mail.x', entity_ids: [], parts: [] })),
})

const valve = {
  organization: '한결밸브',
  department: '영업팀',
  name: '최유진',
  title: '과장',
  email: 'yujin.choi@hangyeol-valve.example',
}
const buyer = { organization: '가람조선', department: '구매팀', name: '정하늘', title: '대리', email: 'haneul.jung@garam-ship.example' }

const draft = (lines = 3, to = [valve], cc = [buyer]): EmailDraft => ({
  to,
  cc,
  subject: '[설계변경 검토] S-001 ECN-D-0038 관련 발주 진행 현황 확인 요청',
  salutation: '한결밸브 최유진 과장님께',
  reference: 'S-001 호선 · ECN-D-0038 밸브 사양 변경',
  paragraphs: [
    paragraph('당사에서 검토 중인 설계변경과 관련하여 요청드립니다.'),
    paragraph('■ 대상 발주', ...Array.from({ length: lines }, (_, i) => `- PO-0${100 + i}`)),
  ],
  sender: '가람조선 설계팀',
  fictional: true,
  translations: [],
})

describe('메일 본문 조립', () => {
  it('인사말 · 관련 건 · 문단(빈 줄로 나눔) · 서명(이름 드림 + 조직)', () => {
    expect(bodyText(draft(1), '손창현')).toBe(
      [
        '한결밸브 최유진 과장님께',
        '',
        '관련 건: S-001 호선 · ECN-D-0038 밸브 사양 변경',
        '',
        '당사에서 검토 중인 설계변경과 관련하여 요청드립니다.',
        '',
        '■ 대상 발주\n- PO-0100',
        '',
        '손창현 드림\n가람조선 설계팀',
      ].join('\n'),
    )
  })

  it('서명 조직이 없으면 이름만, 이름이 비면 담당자', () => {
    expect(bodyText({ ...draft(1), sender: null }, '  ').endsWith('\n담당자 드림')).toBe(true)
  })

  it('복사용 글: 받는 사람·참조·제목 머리, 받는 사람이 없으면 직접 적으라고', () => {
    const text = fullText(draft(1), '손창현')
    expect(text.startsWith('받는 사람: 최유진 과장 <yujin.choi@hangyeol-valve.example>\n참조: 정하늘 대리')).toBe(true)
    expect(text).toContain('제목: [설계변경 검토] S-001')
    expect(fullText(draft(1, [], []), '손창현').startsWith('받는 사람: (직접 입력)\n제목:')).toBe(true)
  })
})

describe('Gmail 쓰기 창 주소', () => {
  it('받는 사람·참조·제목·본문을 인코딩해 채움', () => {
    const url = composeUrl(draft(1), '본문 & 끝')
    expect(url.startsWith('https://mail.google.com/mail/?view=cm&fs=1&to=yujin.choi%40hangyeol-valve.example&cc=')).toBe(
      true,
    )
    const query = new URL(url).searchParams
    expect([query.get('cc'), query.get('su'), query.get('body')]).toEqual([
      'haneul.jung@garam-ship.example',
      '[설계변경 검토] S-001 ECN-D-0038 관련 발주 진행 현황 확인 요청',
      '본문 & 끝',
    ])
  })

  it('본문 없이(null)·받는 사람 없음이면 그 칸을 뺌', () => {
    const url = composeUrl(draft(1, [], []), null)
    expect(url).toBe(`https://mail.google.com/mail/?view=cm&fs=1&su=${encodeURIComponent(draft(1).subject)}`)
  })

  it('짧은 메일은 본문을 주소에 넣고, 한도를 넘으면 본문 없이(클립보드로)', () => {
    const short = planCompose(draft(1), '손창현')
    expect(short.bodyIncluded).toBe(true)
    expect(short.url.length).toBeLessThanOrEqual(URL_LIMIT)
    const long = planCompose(draft(800), '손창현')
    expect(long.bodyIncluded).toBe(false)
    expect(long.url).not.toContain('body=')
    expect(long.body).toContain('- PO-0899')
  })

  it('번역 보기의 제목·본문을 주면 그것으로 채움(1.36.0)', () => {
    const plan = planCompose(draft(1), '손창현', { subject: 'Subject EN', body: 'Body EN' })
    const query = new URL(plan.url).searchParams
    expect([query.get('su'), query.get('body'), plan.body]).toEqual(['Subject EN', 'Body EN', 'Body EN'])
    expect(fullText(draft(1), '손창현', { subject: 'Subject EN', body: 'Body EN' }).endsWith('제목: Subject EN\n\nBody EN')).toBe(
      true,
    )
  })
})

describe('차례로 열기', () => {
  it('다음 차례: 고른 것 중 아직 안 연 첫 초안, 붙여 넣기를 기다리면 멈춤', () => {
    const order = ['a', 'b', 'c']
    expect(nextToOpen(order, new Set(['a', 'c']), {})).toBe('a')
    expect(nextToOpen(order, new Set(['a', 'c']), { a: 'opened' })).toBe('c')
    expect(nextToOpen(order, new Set(['a', 'b']), { a: 'paste' })).toBeNull()
    expect(nextToOpen(order, new Set(['a', 'b']), { a: 'done', b: 'opened' })).toBeNull()
  })
})

describe('접힌 카드의 받는 사람 한 줄', () => {
  it('이름·직함만(주소 없음), 머리 회사와 다른 사람은 회사를 덧붙임, 없으면 직접 입력 안내', () => {
    expect(recipientLine(draft(1), '한결밸브')).toBe('최유진 과장')
    expect(recipientLine(draft(1, [valve, buyer]), '한결밸브')).toBe('최유진 과장, 정하늘 대리 · 가람조선')
    expect(recipientLine(draft(1), '한결밸브')).not.toContain('@')
    expect(recipientLine(draft(1, []), '한결밸브')).toBe('연락처 없음 · 메일 창에서 직접 입력')
  })
})