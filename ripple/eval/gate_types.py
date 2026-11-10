"""관문 사례 입력 모듈(1·2·3단계)이 함께 쓰는 형식."""

from __future__ import annotations

from collections.abc import Callable

AddCase = Callable[..., None]
"""(제목, 초점, [의도,] *연산, 요청 선택 인자) → 사례 하나를 다음 번호로 더한다.

단계마다 인자가 조금 다르다: 1단계는 의도·`confirm_on`, 2단계는 의도·`confirm_on`·`horizon_days`·`cause`·
`outfit_on_board`, 3단계는 의도 없이(강도형 고정) `confirm_on`.
"""
