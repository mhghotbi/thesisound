from __future__ import annotations

from pathlib import Path
from textwrap import dedent, indent


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor not found in {path}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


accounts = Path("src/thesisound/accounts.py")
text = accounts.read_text(encoding="utf-8")
start = text.index("    def verify_password(\n")
end = text.index("\n    def get_active_user(", start)
method = dedent(
    '''\
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
                failed_attempts = (
                    0 if fresh_locked_until is not None else int(fresh[6] or 0)
                )

                if not valid:
                    failed_attempts += 1
                    lockout_until: str | None = None
                    message = _GENERIC_LOGIN_ERROR
                    if failed_attempts >= self.password_login_max_attempts:
                        lockout_until = _timestamp(
                            current_time
                            + timedelta(seconds=self.password_login_lockout_seconds)
                        )
                        message = _LOCKED_LOGIN_ERROR
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
                    raise AccountError(message)

                connection.execute(
                    """
                    UPDATE users
                    SET failed_attempts = 0, locked_until = NULL,
                        last_login_at = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        _timestamp(current_time),
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
    '''
)
accounts.write_text(text[:start] + indent(method, "    ") + text[end:], encoding="utf-8")

app = Path("src/thesisound/web/app.py")
text = app.read_text(encoding="utf-8")
if "import shutil\n" not in text:
    text = text.replace("import secrets\n", "import secrets\nimport shutil\n", 1)
old = dedent(
    '''\
            workspace.save_project(project)
            accounts.add_project_member(
                project.project_id,
                request.state.account.user_id,
                role="owner",
            )
    '''
)
new = dedent(
    '''\
            workspace.save_project(project)
            try:
                accounts.add_project_member(
                    project.project_id,
                    request.state.account.user_id,
                    role="owner",
                )
            except Exception:
                # Project metadata and membership live in independent stores.
                # If membership persistence fails, leaving the freshly-created
                # directory behind creates an invisible orphan and a retry
                # creates a duplicate. Roll back only this brand-new UUID.
                shutil.rmtree(workspace.project_dir(project.project_id), ignore_errors=True)
                raise
    '''
)
if old not in text:
    raise SystemExit("create_project anchor not found")
app.write_text(text.replace(old, new, 1), encoding="utf-8")

store_tests = Path("tests/test_accounts_store.py")
text = store_tests.read_text(encoding="utf-8")
text = text.replace(
    "from pathlib import Path\n",
    "from pathlib import Path\nfrom threading import Event\n",
    1,
)
text = text.replace(
    "import pytest\n\nfrom thesisound.accounts import (",
    "import pytest\n\nimport thesisound.accounts as accounts_module\nfrom thesisound.accounts import (",
    1,
)
text += dedent(
    '''\


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
    '''
)
store_tests.write_text(text, encoding="utf-8")

auth_tests = Path("tests/test_web_project_authorization.py")
text = auth_tests.read_text(encoding="utf-8")
text = text.replace("import re\n", "import ast\nimport re\nimport sqlite3\n", 1)
text = text.replace(
    '            f"/projects/{project_b.project_id}/audio",\n',
    '            f"/projects/{project_b.project_id}/audio",\n'
    '            f"/projects/{project_b.project_id}/readiness",\n',
    1,
)
text += dedent(
    '''\


    def test_failed_membership_write_rolls_back_new_project_directory(
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        app = create_app(_settings(tmp_path))

        def fail_membership(*_args, **_kwargs) -> None:
            raise sqlite3.OperationalError("accounts database unavailable")

        monkeypatch.setattr(app.state.accounts, "add_project_member", fail_membership)

        with TestClient(app, raise_server_exceptions=False) as client:
            _otp_login(client)
            page = client.get("/projects/new")
            response = client.post(
                "/projects",
                data={
                    "csrf_token": _csrf(page.text),
                    "topic": "atomic project creation",
                },
                follow_redirects=False,
            )

        assert response.status_code == 500
        assert app.state.workspace.list_projects() == []
        assert not any(app.state.workspace.root.glob("*/project.json"))


    def test_every_project_scoped_web_handler_has_an_authorization_guard() -> None:
        web_root = Path(__file__).parents[1] / "src" / "thesisound" / "web"
        missing: list[str] = []
        guard_markers = (
            "_project_redirect(request, project_id)",
            "project_redirect(request, project_id)",
            "require_operator(request, project_id)",
            "authenticated_operator(request)",
        )

        for path in sorted(web_root.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not any(argument.arg == "project_id" for argument in node.args.args):
                    continue
                decorators = [
                    ast.get_source_segment(source, item) or ""
                    for item in node.decorator_list
                ]
                if not any(
                    item.startswith("app.get(") or item.startswith("app.post(")
                    for item in decorators
                ):
                    continue
                body = ast.get_source_segment(source, node) or ""
                if not any(marker in body for marker in guard_markers):
                    missing.append(f"{path.name}:{node.lineno}:{node.name}")

        assert missing == []
    '''
)
auth_tests.write_text(text, encoding="utf-8")

replace_once(
    "docs/00-product-scope.md",
    "- multi-tenant یا production-scale باشد.",
    "- سازمان/تیم/workspace چندمستاجری یا production-scale باشد؛ "
    "جداسازی پروژه‌ها در سطح حساب کاربری جزو محصول است.",
)
replace_once(
    "docs/08-security-privacy-copyright.md",
    "- [ ] authentication\n- [ ] per-user project isolation",
    "- [x] authentication (OTP + CLI-provisioned password accounts)\n"
    "- [x] per-user project isolation (member ownership + operator support access)",
)
