"""API 계약을 docs/api/openapi.json으로 내보낸다.

실행: uv run python scripts/export_openapi.py
계약이나 라우터를 바꾸면 다시 실행해 커밋한다(tests/checks/api.py가 최신인지 검사).
"""

from __future__ import annotations

import sys

from ripple.api.app import create_app
from ripple.api.openapi import OPENAPI_PATH, render_openapi
from ripple.config.settings import PROJECT_ROOT


def main() -> int:
    target = PROJECT_ROOT / OPENAPI_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_openapi(create_app()), encoding="utf-8", newline="\n")
    print(f"썼어요: {target.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
