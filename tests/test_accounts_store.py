from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

import thesisound.accounts as accounts_module
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


def test_password_hashing_does_not_hold_sqlite_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "accounts.sqlite3"
    verifier_store = AccountStore(database)
    writer_store = AccountStore(database)
    verifier_store.create_password_user("operator", "secret")

    entered_hash = Event()
    release_hash = Event()
    original_verify = accounts_module.verify_password_hash

    def blocking_verify(password: str, stored: str) -> bool:
        entered_hash.set()
        assert release_hash.wait(timeout=5)
        return original_verify(password, stored)

    monkeypatch.setattr(accounts_module, "verify_password_hash", blocking_verify)

    with ThreadPoolExecutor(max_workers=2) as executor:
        login = executor.submit(verifier_store.verify_password, "operator", "secret")
        assert entered_hash.wait(timeout=1)
        writer = executor.submit(writer_store.set_active, "operator", True)
        try:
            assert writer.result(timeout=1) is None
        finally:
            release_hash.set()
        assert login.result(timeout=5).username == "operator"


def test_concurrent_wrong_password_attempts_preserve_lockout_count(
    tmp_path: Path,
) -> None:
    database = tmp_path / "accounts.sqlite3"
    first = AccountStore(database, password_login_max_attempts=2)
    second = AccountStore(database, password_login_max_attempts=2)
    first.create_password_user("operator", "secret")

    def fail(store: AccountStore) -> str:
        try:
            store.verify_password("operator", "wrong")
        except AccountError as exc:
            return str(exc)
        raise AssertionError("wrong password unexpectedly succeeded")

    with ThreadPoolExecutor(max_workers=2) as executor:
        messages = list(executor.map(fail, (first, second)))

    assert sum("تلاش‌ها" in message for message in messages) == 1
    assert sum("رمز عبور" in message for message in messages) == 1
    with pytest.raises(AccountError, match="تلاش‌ها"):
        first.verify_password("operator", "secret")
