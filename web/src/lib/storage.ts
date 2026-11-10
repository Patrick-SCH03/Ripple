// 이 브라우저에만 남기는 화면 편의 설정(밝기·칸 크기). 사생활 보호 창처럼 저장소가 막혀 있으면
// localStorage에 손대기만 해도 오류가 나므로, 읽기·쓰기 오류를 삼키고 화면은 그대로 동작하게 한다.

function browserStorage(): Storage | undefined {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export const safeStorage: Pick<Storage, 'getItem' | 'setItem'> = {
  getItem: (key) => {
    try {
      return browserStorage()?.getItem(key) ?? null
    } catch {
      return null
    }
  },
  setItem: (key, value) => {
    try {
      browserStorage()?.setItem(key, value)
    } catch {
      // 기억하지 못해도 화면은 동작한다
    }
  },
}
