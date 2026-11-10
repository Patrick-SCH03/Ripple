// 업무 화면 안 어디서나 로그인한 사람과 로그아웃·비밀번호 바꾸기를 쓰게(위 막대 사용자 메뉴·지도 메뉴 권한).
import { createContext, useContext } from 'react'
import type { Me } from '@/api/client'
import type { Session } from './useSession'

export interface SignedIn {
  me: Me
  session: Session
}

export const SessionContext = createContext<SignedIn | null>(null)

export function useSignedIn(): SignedIn {
  const value = useContext(SessionContext)
  if (!value) throw new Error('로그인한 화면 밖에서 사용자 정보 조회')
  return value
}
