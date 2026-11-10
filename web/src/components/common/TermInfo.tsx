// 용어 설명 단추(ⓘ): 누르거나 탭하면 설명이 뜬다(마우스를 올려야만 보이는 정보 금지 — DESIGN.md 9절). 글은 lib/glossary.ts.
import { GLOSSARY, type TermId } from '@/lib/glossary'
import { InfoPop } from './InfoPop'

export function TermInfo({ term }: { term: TermId }) {
  const { title, body } = GLOSSARY[term]
  return <InfoPop title={title} lines={body} />
}
