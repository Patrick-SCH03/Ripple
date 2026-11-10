// 내 건의 반려·보류 사유(최근 결정 감사 줄): 목록 줄 아래 한 줄로 — 고쳐서 다시 올릴 것을 바로 찾게(DESIGN.md 6절).
import { useEffect, useState } from 'react'
import { api, type EcnListItem } from '@/api/client'

/** 반려·보류의 사유를 그 상태 판마다 한 번 읽는다. 열쇠 'ECN@판' — 다시 올려 상태가 바뀌면 옛 사유는 안 보인다. */
export function reasonKey(item: EcnListItem): string {
  return `${item.status.ecn_id}@${item.status.version}`
}

export function useDecisionReasons(items: readonly EcnListItem[]): Record<string, string> {
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const wanted = items
    .filter((item) => item.status.state === 'rejected' || item.status.state === 'on_hold')
    .map(reasonKey)
    .join(',')
  useEffect(() => {
    if (!wanted) return
    let live = true
    for (const key of wanted.split(',')) {
      const ecnId = key.slice(0, key.lastIndexOf('@'))
      api.ecn(ecnId).then(
        (detail) => {
          const last = [...detail.audit].reverse().find((e) => e.action === 'reject' || e.action === 'hold')
          if (live && last?.detail.reason) setReasons((prev) => ({ ...prev, [key]: last.detail.reason ?? '' }))
        },
        () => undefined, // 사유는 보조 정보: 못 읽어도 줄은 그대로
      )
    }
    return () => {
      live = false
    }
  }, [wanted])
  return reasons
}
