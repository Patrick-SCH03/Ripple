import { describe, expect, it } from 'vitest'
import { dispositionName } from './http'

describe('내려받기 파일 이름(Content-Disposition)', () => {
  it('한글 이름(filename*)을 먼저, 없으면 대체 이름', () => {
    const header = `attachment; filename="ripple-analysis-ECN-D-0119-2026-10-26.xlsx"; filename*=UTF-8''${encodeURIComponent('Ripple_분석_ECN-D-0119_2026-10-26.xlsx')}`
    expect(dispositionName(header)).toBe('Ripple_분석_ECN-D-0119_2026-10-26.xlsx')
    expect(dispositionName('attachment; filename="ripple-ledger-2026-10-26.xlsx"')).toBe('ripple-ledger-2026-10-26.xlsx')
    expect(dispositionName('attachment; filename=plain.xlsx')).toBe('plain.xlsx')
  })

  it('잘못 인코딩된 한글 이름이면 대체 이름, 머리글이 없으면 null', () => {
    expect(dispositionName(`attachment; filename="a.xlsx"; filename*=UTF-8''%E0%A4%A`)).toBe('a.xlsx')
    expect(dispositionName(null)).toBeNull()
    expect(dispositionName('attachment')).toBeNull()
  })
})
