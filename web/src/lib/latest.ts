// 최신 요청만 반영하기: 새 요청을 시작하면 이전 요청을 중단하고, 늦게 도착한 이전 응답은 버린다.

export interface Ticket {
  id: number
  signal: AbortSignal
}

export class LatestGate {
  private last = 0
  private controller: AbortController | null = null

  begin(): Ticket {
    this.controller?.abort()
    this.controller = new AbortController()
    this.last += 1
    return { id: this.last, signal: this.controller.signal }
  }

  isLatest(ticket: Ticket): boolean {
    return ticket.id === this.last
  }
}
