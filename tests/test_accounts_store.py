from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from thesisound.accounts import (
    AccountError,
    AccountStore,
    hash_password,
    verify_password_hash,
)


def _store(tmp_path: Path, *, attempts: int = 3, lockout: int = 60) -> AccountStore:
    return AccountStore(
        tmp_path / "accounts.sqlite3",
        password_login_max_attempts=attempts,
        password_login_lockout_seconds=lockout,
    )


def test_password_hash_round_trip() -> None:
    stored = hash_password("correct horse battery staple")

    assert stored.startswith("pbkdf2_sha256$600000$")
    assert verify_password_hash("correct horse battery staple", stored)
    assert not verify_password_hash("wrong", stored)
    assert not verify_password_hash("anything", "malformed")


def test_phone_account_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.get_or_create_phone_user("09120000000")
    second = store.get_or_create_phone_user("09120000000")

    assert first == second
    assert first.role == "member"
    assert first.phone == "09120000000"
    assert first.username is None


def test_phone_account_is_safe_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "accounts.sqlite3"
    first_store = AccountStore(database)
    second_store = AccountStore(database)

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = list(
            executor.map(
                lambda store: store.get_or_create_phone_user("09120000000"),
                (first_store, second_store),
            )
        )

    assert records[0] == records[1]


def test_generic_login_failures_are_indistinguishable(tmp_path: Path) -> None:
    store = _store(tmp_path, attempts=10)
    account = store.create_password_user("operator", "secret")

    with pytest.raises(AccountError) as wrong:
        store.verify_password("operator", "wrong")
    with pytest.raises(AccountError) as unknown:
        store.verify_password("missing", "wrong")
    store.set_active("operator", False)
    with pytest.raises(AccountError) as inactive:
        store.verify_password("operator", "secret")

    assert str(wrong.value) == str(unknown.value) == str(inactive.value)
    assert store.get_active_user(account.user_id) is None


def test_password_login_locks_then_recovers(tmp_path: Path) -> None:
    store = _store(tmp_path, attempts=2, lockout=60)
    store.create_password_user("operator", "secret")
    now = datetime(2026, 8, 9, 18, 0, tzinfo=UTC)

    with pytest.raises(AccountError, match="رمز عبور"):
        store.verify_password("operator", "wrong", now=now)
    with pytest.raises(AccountError, match="تلاش‌ها"):
        store.verify_password("operator", "wrong", now=now)
    with pytest.raises(AccountError, match="تلاش‌ها"):
        store.verify_password("operator", "secret", now=now + timedelta(seconds=30))

    with pytest.raises(AccountError, match="رمز عبور"):
        store.verify_password("operator", "wrong", now=now + timedelta(seconds=61))
    with pytest.raises(AccountError, match="تلاش‌ها"):
        store.verify_password("operator", "wrong", now=now + timedelta(seconds=62))

    account = store.verify_password("operator", "secret", now=now + timedelta(seconds=123))
    assert account.username == "operator"


def test_membership_queries_are_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account = store.get_or_create_phone_user("09120000000")
    project_id = "0e3ec60e-365e-4d48-aab4-268f65c67dbc"

    assert not store.has_any_member(project_id)
    store.add_project_member(project_id, account.user_id)
    store.add_project_member(project_id, account.user_id)

    assert store.has_any_member(project_id)
    assert store.is_project_member(project_id, account.user_id)
    assert store.project_ids_for_user(account.user_id) == {project_id}
