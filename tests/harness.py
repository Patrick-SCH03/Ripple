"""성질 검사 도구: ✓/✗ 출력과 종료 코드. 외부 테스트 프레임워크 없이 돈다."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# 해요체(~어요·~예요…)·합니다체(~니다) 끝맺음. '필요'·'주요'·'소요'처럼 명사로 끝나는 '요'는 뺀다
_POLITE_END = re.compile(r"((?<![필주소중개수강])요|니다)[.?!]?$")


def nominal(text: str) -> bool:
    """서버 문구가 명사형·개조식인지: 비지 않고, 해요체·합니다체 끝맺음과 끝 마침표가 없다."""
    stripped = text.strip()
    return bool(stripped) and not stripped.endswith(".") and not _POLITE_END.search(stripped)


@dataclass
class Checker:
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def section(self, title: str) -> None:
        print(f"\n[{title}]")

    def check(self, name: str, cond: bool, detail: object = "") -> None:
        if cond:
            self.passed += 1
            print("  ✓", name)
        else:
            self.failed += 1
            self.failures.append(name)
            print("  ✗", name, detail)

    @staticmethod
    def raises(fn: Callable[[], object], exc: type[BaseException] = ValueError) -> bool:
        """fn이 exc를 던지면 True. Pydantic 검증 실패(ValidationError)는 ValueError다."""
        try:
            fn()
        except exc:
            return True
        return False
