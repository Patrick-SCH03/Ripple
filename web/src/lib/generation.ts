// 화면 세대: 상세에 보일 분석을 사용자가 바꿀 때마다(설계변경 고르기, 확정일·요청 JSON·보류 바꾸기, 비서 새 대화,
// 지난 분석 직접 열기) 하나 올린다. 비서는 보낼 때 세대를 잡아 두고, 분석한 차례가 도착했을 때 세대가 그대로일
// 때만 상세를 바꾼다(늦게 온 응답이 사용자가 방금 고른 것을 덮지 않게).

export class ScreenGeneration {
  private value = 0

  get current(): number {
    return this.value
  }

  bump(): number {
    this.value += 1
    return this.value
  }

  isCurrent(stamp: number): boolean {
    return stamp === this.value
  }
}
