// 첫 그림 전에 밝기를 적용한다(src/lib/theme.ts의 resolveTheme과 같은 규칙). 소개 화면은 밝게만(useLightOnly) — 로그인·
// 업무 화면(/login, /app…)이 아닌 주소는 모두 소개로 가므로(lib/route.ts parseRoute) 그 주소도 밝게 시작한다.
// 인라인 스크립트가 아니라 파일로 두어 배포의 CSP를 script-src 'self'로 지킨다(web/Caddyfile).
;(function () {
  var choice = null
  try {
    choice = window.localStorage.getItem('ripple.theme')
  } catch {
    // 저장소를 못 쓰면(사생활 보호 창 등) 기본값(밝게)
  }
  var landing = !/^\/(login|app)(\/|$)/.test(window.location.pathname)
  var dark =
    !landing && (choice === 'dark' || (choice === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches))
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
})()
