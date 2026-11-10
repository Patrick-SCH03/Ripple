"""계정 도구(로컬·오프라인 설치용). 비밀번호는 숨김 입력으로만 받는다(명령줄 인자·환경 변수로 받지 않음).

  uv run python -m ripple.auth add-admin <아이디> [이름]     관리자 추가(첫 로그인 때 비밀번호를 바꾸지 않음)
  uv run python -m ripple.auth reset <아이디>               임시 비밀번호 발급(화면에 한 번 보임, 첫 로그인 때 바꿈)
  uv run python -m ripple.auth list                         계정 목록

데이터 폴더는 RIPPLE_DATA_DIR(기본 <프로젝트>/.data). API가 켜져 있으면 끈 뒤에 쓴다(서버는 시작할 때 파일을 읽는다).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, datetime

from ripple.config.settings import Settings
from ripple.contracts.auth import Role
from ripple.store.accounts import AccountStore, SessionStore, StoredAccount

from .passwords import hash_password, password_problem, temporary_password
from .principal import RESERVED_IDS, normalize_id, valid_login_id


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    root = Settings.from_env().data_dir
    accounts = AccountStore(root)
    accounts.load()
    sessions = SessionStore(root)
    sessions.load(datetime.now(UTC))

    if args.command == "list":
        return _list(accounts)

    key = normalize_id(args.login_id)
    if not valid_login_id(key) or key in RESERVED_IDS:
        print("아이디는 영문 소문자·숫자로 시작하는 3~32자(._- 가능)여야 합니다", file=sys.stderr)
        return 2

    if args.command == "add-admin":
        return _add_admin(accounts, key, args.name)
    return _reset(accounts, sessions, key)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ripple.auth", description="Ripple 계정 도구")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-admin", help="관리자 추가")
    add.add_argument("login_id")
    add.add_argument("name", nargs="?", default="팀장")
    reset = commands.add_parser("reset", help="임시 비밀번호 발급")
    reset.add_argument("login_id")
    commands.add_parser("list", help="계정 목록")
    return parser


def _list(accounts: AccountStore) -> int:
    for account in accounts.all():
        print(f"{account.login_id}\t{account.name}\t{account.role.value}\t{_state(account)}")
    return 0


def _add_admin(accounts: AccountStore, key: str, name: str) -> int:
    """관리자 추가: 비밀번호를 숨김 입력으로 두 번 받는다."""
    if accounts.get(key) is not None:
        print("이미 있는 아이디입니다", file=sys.stderr)
        return 2
    if accounts.is_retired(key):
        print("삭제한 계정의 아이디는 다시 사용할 수 없습니다", file=sys.stderr)
        return 2
    password = getpass.getpass("비밀번호(입력이 보이지 않습니다): ")
    problem = password_problem(password, key)
    if problem is None and getpass.getpass("한 번 더: ") != password:
        problem = "두 번 입력한 비밀번호가 다릅니다"
    if problem:
        print(problem, file=sys.stderr)
        return 2
    account = StoredAccount(
        login_id=key,
        name=name,
        role=Role.ADMIN,
        password_hash=hash_password(password),
        created_at=datetime.now(UTC),
    )
    accounts.change(lambda stored: stored.__setitem__(key, account))
    print(f"관리자 {key}를 만들었습니다")
    return 0


def _reset(accounts: AccountStore, sessions: SessionStore, key: str) -> int:
    """임시 비밀번호 발급: 세션 판을 올리고 그 계정의 세션을 지운다."""
    current = accounts.get(key)
    if current is None:
        print("없는 계정입니다", file=sys.stderr)
        return 2
    temporary = temporary_password()
    updated = current.model_copy(
        update={
            "password_hash": hash_password(temporary),
            "must_change_password": True,
            "session_version": current.session_version + 1,
        }
    )
    accounts.change(lambda stored: stored.__setitem__(key, updated))
    sessions.delete_for(key, below=updated.session_version)
    print(f"임시 비밀번호(이 화면에서만 보여요): {temporary}")
    return 0


def _state(account: StoredAccount) -> str:
    if account.disabled:
        return "꺼짐"
    return "비밀번호 바꾸기 전" if account.must_change_password else "사용 중"


if __name__ == "__main__":
    sys.exit(main())
