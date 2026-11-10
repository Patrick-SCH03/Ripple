// 변경 원인 안내(상세 머리 아래): 제목 한 줄 + 굵은 핵심 구절로 시작하는 짧은 항목(글은 lib/causeNote.ts).
// 보조 글자색으로 두고 핵심 구절만 본문 색으로 굵게 — 훑어 읽어도 무엇을 어떻게 계산했고 어디를 보면 되는지 잡히게.
import { causeNote } from '@/lib/causeNote'
import type { ChangeCause } from '@/lib/request'

export function CauseNote({ cause }: { cause: ChangeCause | null | undefined }) {
  const note = causeNote(cause)
  if (!note) return null
  return (
    <section
      aria-label="변경 원인 안내"
      className="mt-2 text-sm text-foreground-secondary"
      data-testid={cause === 'owner_request' ? 'owner-request-note' : 'permissible-delay-note'}
    >
      <p className="font-medium text-foreground">{note.title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 marker:text-muted-foreground">
        {note.items.map((item) => (
          <li key={item.lead}>
            <strong className="font-semibold text-foreground">{item.lead}</strong> {item.text}
          </li>
        ))}
      </ul>
    </section>
  )
}
