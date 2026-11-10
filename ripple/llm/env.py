"""어댑터가 키를 읽는 .env 파일(저장소 루트, 깃 제외). 값은 로그·기록에 남기지 않는다."""

from __future__ import annotations

from pathlib import Path


def read_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE 줄만 읽는다(따옴표 벗김, 주석·빈 줄 무시). 파일이 없으면 빈 묶음."""
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found
