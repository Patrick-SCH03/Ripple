// 받은 파일(엑셀 내보내기)을 이 브라우저의 내려받기로 저장한다. 서버가 준 Blob을 그대로 쓴다.

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
