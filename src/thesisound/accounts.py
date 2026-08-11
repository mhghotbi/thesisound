from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from thesisound.config import Settings

_PBKDF2_ITERATIONS = 600_000
_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_GENERIC_LOGIN_ERROR = "نام کاربری یا رمز عبور درست نیست."
_LOCKED_LOGIN_ERROR = "تعداد تلاش‌ها بیش از حد مجاز است. بعداً دوباره تلاش کنید."
_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$00000000000000000000000000000000$"
    "e53ec9577531570ec665a5e44bcc558cb2532ab74c8f728d4ac475b0b911fc62"
)


class AccountError(ValueError):
    """User-actionable account or authentication error."""


class AccountLockedError(AccountError):
    """Raised when a login lockout is newly triggered."""


@dataclass(frozen=True, slots=True)
class AccountRecord:
    user_id: int
    role: str
    phone: str | None
    username: str | None

    @property
    def label(self) -> str:
        return self.username or self.phone or str(self.user_id)


def hash_password(password: str) -> str:
    if not password:
        raise AccountError("رمز عبور نمی‌تواند خالی باشد.")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"{_PASSWORD_ALGORITHM}${_PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password_hash(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, hash_hex = stored.split("$")
        if algorithm != _PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        if iterations < 1:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (TypeError, ValueError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


class AccountStore:
    """Durable account and project-membership store backed by SQLite."""

    def __init__(
        self,
        database_path: Path,
        *,
        password_login_max_attempts: int = 5,
        password_login_lockout_seconds: int = 900,
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.password_login_max_attempts = password_login_max_attempts
        self.password_login_lockout_seconds = password_login_lockout_seconds
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def create_password_user(
        self,
        username: str,
        password: str,
        *,
        role: str = "operator",
    ) -> AccountRecord:
        normalized = _normalize_username(username)
        if role not in {"operator", "member"}:
            raise AccountError("نقش حساب معتبر نیست.")
        password_hash = hash_password(password)
        now = _timestamp(_now())
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users(
                        role, username, password_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (role, normalized, password_hash, now, now),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise AccountError("این نام کاربری قبلاً ثبت شده است.") from exc
        return AccountRecord(user_id=user_id, role=role, phone=None, username=normalized)

    def get_or_create_phone_user(self, phone: str) -> AccountRecord:
        normalized = phone.strip()
        if not normalized:
            raise AccountError("شماره موبایل معتبر نیست.")
        now = _timestamp(_now())
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO users(role, phone, created_at, updated_at)
                VALUES ('member', ?, ?, ?)
                """,
                (normalized, now, now),
            )
            row = connection.execute(
                "SELECT user_id, role, phone, username FROM users WHERE phone = ?",
                (normalized,),
            ).fetchone()
        assert row is not None
        return _record_from_row(row)

    def verify_password(
        self,
        username: str,
        password: str,
        *,
        now: datetime | None = None,
    ) -> AccountRecord:
        try:
            normalized = _normalize_username(username)
        except AccountError:
            verify_password_hash(password, _DUMMY_PASSWORD_HASH)
            raise AccountError(_GENERIC_LOGIN_ERROR) from None

        current_time = (now or _now()).astimezone(UTC)
        # PBKDF2 is intentionally performed outside BEGIN IMMEDIATE. SQLite has
        # one writer at a time; holding that lock for a 600k-iteration hash
        # serializes unrelated logins/account writes and makes unknown-user
        # traffic an avoidable write-lock denial of service. We optimistically
        # read, hash, then re-check the security-relevant row under a short
        # write transaction. If another process changed it meanwhile, retry
        # against the fresh state rather than applying a stale decision.
        while True:
            with self._lock, closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT user_id, role, phone, username, password_hash, is_active,
                           failed_attempts, locked_until
                    FROM users WHERE username = ?
                    """,
                    (normalized,),
                ).fetchone()

            if row is None:
                verify_password_hash(password, _DUMMY_PASSWORD_HASH)
                raise AccountError(_GENERIC_LOGIN_ERROR)

            locked_until = _parse_timestamp(row[7])
            if locked_until is not None and current_time < locked_until:
                raise AccountError(_LOCKED_LOGIN_ERROR)

            if not bool(row[5]):
                verify_password_hash(password, row[4] or _DUMMY_PASSWORD_HASH)
                raise AccountError(_GENERIC_LOGIN_ERROR)

            password_hash = str(row[4]) if row[4] is not None else None
            valid = bool(password_hash) and verify_password_hash(password, password_hash)

            with self._lock, closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                fresh = connection.execute(
                    """
                    SELECT user_id, role, phone, username, password_hash, is_active,
                           failed_attempts, locked_until
                    FROM users WHERE username = ?
                    """,
                    (normalized,),
                ).fetchone()

                # Account deletion or any concurrent security-state change
                # invalidates the decision made from the optimistic read.
                if fresh is None:
                    connection.rollback()
                    raise AccountError(_GENERIC_LOGIN_ERROR)
                if tuple(fresh[4:8]) != tuple(row[4:8]):
                    connection.rollback()
                    continue

                fresh_locked_until = _parse_timestamp(fresh[7])
                failed_attempts = 0 if fresh_locked_until is not None else int(fresh[6] or 0)

                if not valid:
                    failed_attempts += 1
                    lockout_until: str | None = None
                    message = _GENERIC_LOGIN_ERROR
                    newly_locked = False
                    if failed_attempts >= self.password_login_max_attempts:
                        lockout_until = _timestamp(
                            current_time + timedelta(seconds=self.password_login_lockout_seconds)
                        )
                        message = _LOCKED_LOGIN_ERROR
                        newly_locked = True
                    connection.execute(
                        """
                        UPDATE users
                        SET failed_attempts = ?, locked_until = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (
                            failed_attempts,
                            lockout_until,
                            _timestamp(current_time),
                            int(fresh[0]),
                        ),
                    )
                    connection.commit()
                    if newly_locked:
                        raise AccountLockedError(message)
                    raise AccountError(message)

                connection.execute(
                    """
                    UPDATE users
                    SET failed_attempts = 0, locked_until = NULL, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        _timestamp(current_time),
                        int(fresh[0]),
                    ),
                )
                connection.commit()
                return AccountRecord(
                    user_id=int(fresh[0]),
                    role=str(fresh[1]),
                    phone=fresh[2],
                    username=fresh[3],
                )

    def get_active_user(self, user_id: int) -> AccountRecord | None:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT user_id, role, phone, username
                FROM users WHERE user_id = ? AND is_active = 1
                """,
                (user_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def get_user_by_username(self, username: str) -> AccountRecord | None:
        normalized = _normalize_username(username)
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT user_id, role, phone, username FROM users WHERE username = ?",
                (normalized,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def set_password(self, username: str, password: str) -> None:
        normalized = _normalize_username(username)
        password_hash = hash_password(password)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET password_hash = ?, failed_attempts = 0, locked_until = NULL,
                    updated_at = ?
                WHERE username = ?
                """,
                (password_hash, _timestamp(_now()), normalized),
            )
            if cursor.rowcount != 1:
                raise AccountError("حساب کاربری پیدا نشد.")

    def set_active(self, username: str, is_active: bool) -> None:
        normalized = _normalize_username(username)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET is_active = ?, failed_attempts = 0, locked_until = NULL,
                    updated_at = ?
                WHERE username = ?
                """,
                (int(is_active), _timestamp(_now()), normalized),
            )
            if cursor.rowcount != 1:
                raise AccountError("حساب کاربری پیدا نشد.")

    def is_project_member(self, project_id: UUID | str, user_id: int) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?",
                (str(project_id), user_id),
            ).fetchone()
        return row is not None

    def add_project_member(
        self,
        project_id: UUID | str,
        user_id: int,
        *,
        role: str = "owner",
    ) -> None:
        if not role.strip():
            raise AccountError("نقش عضویت پروژه معتبر نیست.")
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_members(
                        project_id, user_id, role, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (str(project_id), user_id, role.strip(), _timestamp(_now())),
                )
            except sqlite3.IntegrityError as exc:
                raise AccountError("حساب کاربری پیدا نشد.") from exc

    def project_ids_for_user(self, user_id: int) -> set[str]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT project_id FROM project_members WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def has_any_member(self, project_id: UUID | str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT 1 FROM project_members WHERE project_id = ? LIMIT 1",
                (str(project_id),),
            ).fetchone()
        return row is not None

    def record_login(self, user_id: int, *, now: datetime | None = None) -> bool:
        """Set last_login_at. Returns True if this is the first login."""

        current_time = (now or _now()).astimezone(UTC)
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT last_login_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise AccountError("حساب کاربری پیدا نشد.")
            is_first = row[0] is None
            connection.execute(
                """
                UPDATE users
                SET last_login_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (_timestamp(current_time), _timestamp(current_time), user_id),
            )
        return is_first

    def primary_user_id_for_project(self, project_id: UUID | str) -> int | None:
        """Resolve the denormalized user for a project, preferring role=owner."""

        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT user_id FROM project_members
                 WHERE project_id = ?
                 ORDER BY CASE WHEN role = 'owner' THEN 0 ELSE 1 END, user_id
                 LIMIT 1
                """,
                (str(project_id),),
            ).fetchone()
        return int(row[0]) if row else None

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta("
                "  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current > len(_MIGRATIONS):
                raise RuntimeError(
                    f"Account schema v{current} is newer than this build supports "
                    f"(v{len(_MIGRATIONS)}). Upgrade Thesisound or point at another database."
                )
            for index in range(current, len(_MIGRATIONS)):
                migration = _MIGRATIONS[index]
                if callable(migration):
                    migration(connection)
                else:
                    connection.executescript(migration)
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(index + 1),),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection


def accounts_store_from_settings(settings: Settings) -> AccountStore:
    return AccountStore(
        settings.resolved_accounts_database_path,
        password_login_max_attempts=settings.password_login_max_attempts,
        password_login_lockout_seconds=settings.password_login_lockout_seconds,
    )


def _normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not normalized:
        raise AccountError("نام کاربری نمی‌تواند خالی باشد.")
    return normalized


def _record_from_row(row: sqlite3.Row | tuple[object, ...]) -> AccountRecord:
    return AccountRecord(
        user_id=int(row[0]),
        role=str(row[1]),
        phone=str(row[2]) if row[2] is not None else None,
        username=str(row[3]) if row[3] is not None else None,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users(
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role            TEXT NOT NULL CHECK (role IN ('operator', 'member')),
    phone           TEXT UNIQUE,
    username        TEXT UNIQUE,
    password_hash   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_login_at   TEXT,
    CHECK (
        (phone IS NOT NULL AND username IS NULL AND password_hash IS NULL) OR
        (phone IS NULL AND username IS NOT NULL AND password_hash IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS project_members(
    project_id  TEXT NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'owner',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id);
"""

_MIGRATIONS: tuple[str | Callable[[sqlite3.Connection], None], ...] = (_SCHEMA_V1,)
