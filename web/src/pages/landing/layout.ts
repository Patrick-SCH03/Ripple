// 소개 화면 판의 공통 폭·제목·큰 단추 클래스(DESIGN.md 12절 소개 화면 전용 값). 넓은 화면은 가로를 꽉 채우는 구성(좌우 여백만).

/** 글 묶음 폭(첫 화면 제목·설명). */
export const WIDTH = 'mx-auto max-w-[1120px] px-4 sm:px-6'
/** 화면 폭을 거의 다 쓰는 판(좌우 여백 16 · 24 · 32 · 40px, 아주 넓은 창은 1840px에서 멈춤). */
export const FULL = 'mx-auto w-full max-w-[1920px] px-4 sm:px-6 lg:px-8 xl:px-10'
export const TITLE = 'text-title-sm font-bold tracking-tight text-balance md:text-title lg:text-display-md xl:text-display'
export const BIG_BUTTON = 'h-12 w-full px-6 text-md font-semibold sm:w-auto'
