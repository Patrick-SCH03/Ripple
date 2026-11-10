// 한 번 읽어 보이기만 하는 데이터(관리 대화상자 본문): 부품이 사라진 뒤 온 응답은 버린다. load가 바뀌면 다시 읽고,
// 처음부터 다시 읽으려면 부르는 쪽이 key로 부품을 새로 만든다(이전 값·오류가 남지 않게).
import { useEffect, useState } from 'react'
import { ApiError } from '@/api/client'

export interface Fetched<T> {
  data: T | null
  error: string | null
}

export function useFetched<T>(load: () => Promise<T>): Fetched<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    load().then(
      (result) => live && setData(result),
      (caught: unknown) => live && setError(caught instanceof ApiError ? caught.message : String(caught)),
    )
    return () => {
      live = false
    }
  }, [load])
  return { data, error }
}
