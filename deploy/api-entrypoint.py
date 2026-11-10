"""API 컨테이너 시작(docs/operations.md(배포)).

데이터 폴더가 root 소유 볼륨으로 붙어도 ripple 사용자가 쓰게 맞춘 뒤 권한을 낮춰 실행한다.

- Railway 볼륨은 root 소유로 붙고(공식 문서는 RAILWAY_RUN_UID=0으로 root 실행을 권함) compose 볼륨은 이미지의 소유권을
  따른다. 어느 쪽이든 root로 시작해 RIPPLE_DATA_DIR 안에서 ripple이 아닌 것만 ripple로 바꾸고, 그 뒤 setgid·setuid로
  ripple이 되어 명령을 실행한다(서버는 root 권한 없이 돈다).
- 이미 ripple로 시작했으면(docker run --user 등) 그대로 실행한다.
- 표준 라이브러리만 쓴다(이미지에 setpriv·gosu를 따로 넣지 않으려고).
"""

from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path

USER = "ripple"


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit("실행할 명령이 없어요")
    if os.getuid() == 0:
        user = pwd.getpwnam(USER)
        data = Path(os.environ.get("RIPPLE_DATA_DIR", "/app/.data"))
        data.mkdir(parents=True, exist_ok=True)
        for path in [data, *data.rglob("*")]:
            if path.lstat().st_uid != user.pw_uid:
                os.lchown(path, user.pw_uid, user.pw_gid)
        os.setgroups([])
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
        os.environ["HOME"] = user.pw_dir
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main(sys.argv[1:])
