from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    if new in content:
        return
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one anchor in {path!r}, found {count}")
    write(path, content.replace(old, new, 1))


write(
    "src/thesisound/services/url_probe.py",
    '''from __future__ import annotations

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from thesisound.config import Settings
from thesisound.http_proxy import normalize_proxy_url

_DEAD_STATUSES = {404, 410, 451}


@dataclass(frozen=True, slots=True)
class UrlProbeResult:
    url: str
    outcome: Literal["reachable", "dead", "unknown"]
    http_status: int | None
    reason: str


def probe_url(
    url: str,
    *,
    settings: Settings,
    opener: OpenerDirector | None = None,
) -> UrlProbeResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return UrlProbeResult(url, "dead", None, "unsupported URL scheme")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)
    except OSError as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)

    for entry in addresses:
        address = entry[4][0].split("%", 1)[0]
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError:
            return UrlProbeResult(url, "unknown", None, "invalid resolved address")
        if (
            resolved.is_loopback
            or resolved.is_private
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_multicast
        ):
            return UrlProbeResult(url, "dead", None, "non-public host")

    active_opener = opener or _build_opener(settings)
    try:
        head_status = _request_status(
            active_opener,
            url,
            method="HEAD",
            timeout=settings.url_probe_timeout_seconds,
        )
        mapped = _map_status(url, head_status)
        if mapped is not None:
            return mapped
        get_status = _request_status(
            active_opener,
            url,
            method="GET",
            timeout=settings.url_probe_timeout_seconds,
        )
        mapped = _map_status(url, get_status)
        if mapped is not None:
            return mapped
        return UrlProbeResult(url, "unknown", get_status, f"HTTP {get_status}")
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)


def _build_opener(settings: Settings) -> OpenerDirector:
    proxy = normalize_proxy_url(settings.http_proxy)
    proxies = {"http": proxy, "https": proxy} if proxy is not None else {}
    return build_opener(ProxyHandler(proxies))


def _request_status(
    opener: OpenerDirector,
    url: str,
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
) -> int:
    headers = {"Range": "bytes=0-0"} if method == "GET" else {}
    request = Request(url, method=method, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            if method == "GET":
                response.read(16)
            return int(getattr(response, "status", response.getcode()))
    except HTTPError as exc:
        return int(exc.code)


def _map_status(url: str, status: int) -> UrlProbeResult | None:
    if status in _DEAD_STATUSES:
        return UrlProbeResult(url, "dead", status, f"HTTP {status}")
    if 200 <= status < 400:
        return UrlProbeResult(url, "reachable", status, f"HTTP {status}")
    return None
''',
)

write(
    "src/thesisound/services/web_search_cache.py",
    '''from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from thesisound import tracing
from thesisound.config import Settings
from thesisound.domain import SearchQuery
from thesisound.ports import RawSearchResult


class WebSearchCache:
    def __init__(
        self,
        workspace_root: Path,
        settings: Settings,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = workspace_root / "_shared" / "web-search"
        self.settings = settings
        self.now = now or (lambda: datetime.now(UTC))

    def load(
        self,
        project_id: UUID,
        query: SearchQuery,
    ) -> list[RawSearchResult] | None:
        query_hash = self._query_hash(query)
        path = self.root / f"{query_hash}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if self.now() - created_at > timedelta(
                hours=self.settings.web_search_cache_ttl_hours
            ):
                return self._miss(project_id)
            if payload["query_hash"] != query_hash:
                return self._miss(project_id)
            if payload["model"] != self.settings.model_fast:
                return self._miss(project_id)
            results = [RawSearchResult.model_validate(item) for item in payload["results"]]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self._miss(project_id)
        tracing.event(
            "cache.lookup",
            component="cache",
            project_id=project_id,
            cache="web_search",
            result="hit",
        )
        return results

    def save(self, query: SearchQuery, results: list[RawSearchResult]) -> None:
        query_hash = self._query_hash(query)
        path = self.root / f"{query_hash}.json"
        temporary = path.with_suffix(".json.tmp")
        payload = {
            "created_at": self.now().isoformat(),
            "query_hash": query_hash,
            "model": self.settings.model_fast,
            "results": [item.model_dump(mode="json") for item in results],
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            return

    def path_for(self, query: SearchQuery) -> Path:
        return self.root / f"{self._query_hash(query)}.json"

    def _query_hash(self, query: SearchQuery) -> str:
        payload = json.dumps(
            {
                "query": query.model_dump(mode="json"),
                "model": self.settings.model_fast,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _miss(project_id: UUID) -> None:
        tracing.event(
            "cache.lookup",
            component="cache",
            project_id=project_id,
            cache="web_search",
            result="miss",
        )
        return None
''',
)

replace_once(
    "src/thesisound/config.py",
    "    search_timeout_seconds: int = Field(default=120, ge=5, le=3_600)\n",
    "    search_timeout_seconds: int = Field(default=120, ge=5, le=3_600)\n"
    "    url_probe_enabled: bool = True\n"
    "    url_probe_timeout_seconds: int = Field(default=10, ge=1, le=60)\n"
    "    web_search_cache_ttl_hours: int = Field(default=24, ge=1, le=720)\n",
)
replace_once(
    ".env.example",
    "# =============================================================================\n# Provider execution and retry policy\n",
    "# =============================================================================\n"
    "# Source discovery\n"
    "# =============================================================================\n\n"
    "THESISOUND_URL_PROBE_ENABLED=true\n"
    "THESISOUND_URL_PROBE_TIMEOUT_SECONDS=10\n"
    "THESISOUND_WEB_SEARCH_CACHE_TTL_HOURS=24\n\n"
    "# =============================================================================\n# Provider execution and retry policy\n",
)
replace_once(
    "src/thesisound/http_proxy.py",
    '''"""Gemini-only outbound HTTP(S) proxy helpers.\n\nOkian and other non-Gemini clients must not inherit this proxy.\n"""\n''',
    '''"""Gemini-scoped outbound HTTP(S) proxy helpers.\n\nOkian and other non-Gemini clients must not inherit this proxy. The URL probe\ndeliberately reuses it so local reachability follows the operator's internet path;\nGemini URL Context itself still fetches from Google's network.\n"""\n''',
)

replace_once(
    "src/thesisound/web/source_discovery.py",
    "from thesisound.adapters.search.gemini import GeminiWebSearchPort\n",
    "from thesisound import tracing\n"
    "from thesisound.adapters.search.gemini import GeminiWebSearchPort\n",
)
replace_once(
    "src/thesisound/web/source_discovery.py",
    "from thesisound.prompt_loader import PromptLoader\n",
    "from thesisound.ports import RawSearchResult\n"
    "from thesisound.prompt_loader import PromptLoader\n",
)
replace_once(
    "src/thesisound/web/source_discovery.py",
    "from thesisound.services.model_runner import ModelRunner\n",
    "from thesisound.services.model_runner import ModelRunner\n"
    "from thesisound.services.url_probe import probe_url\n"
    "from thesisound.services.web_search_cache import WebSearchCache\n",
)
old_search = '''        normalized = query.strip() or project.brief.central_question\n        model_port = GeminiStructuredModel(\n            api_keys=self.settings.gemini_api_keys,\n            settings=self.settings,\n        )\n        search_port = GeminiWebSearchPort(\n            model_port,\n            model=self.settings.model_fast,\n            project_id=project.project_id,\n            timeout_ms=self.settings.search_timeout_seconds * 1000,\n            max_provider_attempts=self.settings.provider_max_attempts,\n            provider_retry_base_seconds=self.settings.provider_retry_base_seconds,\n        )\n        results = search_port.search(\n            SearchQuery(\n                query=normalized,\n                provider="web",\n                source_role=SourceRole.REFERENCE,\n                language=project.brief.output_language,\n                purpose=(\n                    "Find credible sources that can materially support the project's "\n                    "central question and declared scope."\n                ),\n                priority=3,\n            )\n        )\n'''
new_search = '''        normalized = query.strip() or project.brief.central_question\n        search_query = SearchQuery(\n            query=normalized,\n            provider="web",\n            source_role=SourceRole.REFERENCE,\n            language=project.brief.output_language,\n            purpose=(\n                "Find credible sources that can materially support the project's "\n                "central question and declared scope."\n            ),\n            priority=3,\n        )\n        cache = WebSearchCache(self.workspace.root, self.settings)\n        results = cache.load(project.project_id, search_query)\n        if results is None:\n            model_port = GeminiStructuredModel(\n                api_keys=self.settings.gemini_api_keys,\n                settings=self.settings,\n            )\n            search_port = GeminiWebSearchPort(\n                model_port,\n                model=self.settings.model_fast,\n                project_id=project.project_id,\n                timeout_ms=self.settings.search_timeout_seconds * 1000,\n                max_provider_attempts=self.settings.provider_max_attempts,\n                provider_retry_base_seconds=self.settings.provider_retry_base_seconds,\n            )\n            results = search_port.search(search_query)\n            cache.save(search_query, results)\n'''
replace_once("src/thesisound/web/source_discovery.py", old_search, new_search)
replace_once(
    "src/thesisound/web/source_discovery.py",
    '''    ) -> UiSourceManifest:\n        source_id = uuid4()\n        runner = ModelRunner(\n''',
    '''    ) -> UiSourceManifest:\n        if self.settings.url_probe_enabled:\n            probe = probe_url(str(candidate.url), settings=self.settings)\n            if probe.outcome == "dead":\n                tracing.event(\n                    "source.probe_blocked",\n                    component="source",\n                    project_id=project_id,\n                    level="warn",\n                    reason=probe.reason,\n                    http_status=probe.http_status,\n                )\n                return UiSourceManifest(\n                    source_id=uuid4(),\n                    filename=_web_filename(candidate.title),\n                    display_title=candidate.title,\n                    content_type="text/markdown",\n                    size_bytes=0,\n                    status=UiSourceStatus.BLOCKED,\n                    issue_summary=(\n                        "نشانی منبع به‌طور قطعی در دسترس نیست و پیش از مصرف مدل "\n                        "مسدود شد."\n                    ),\n                    origin="gemini_web_search",\n                    canonical_url=str(candidate.url),\n                    retrieval_scope="unavailable",\n                    quality_issues=[probe.reason],\n                )\n        source_id = uuid4()\n        runner = ModelRunner(\n''',
)

write(
    "tests/test_url_probe.py",
    '''from __future__ import annotations

import socket
from urllib.request import ProxyHandler, Request

import pytest

from thesisound.config import Settings
from thesisound.services import url_probe
from thesisound.services.url_probe import probe_url


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.read_bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        self.read_bytes = size
        return b"x"


class FakeOpener:
    def __init__(self, outcomes: list[int | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Request] = []

    def open(self, request: Request, *, timeout: int):
        assert timeout > 0
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        url_probe.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, http_proxy="none", **overrides)


@pytest.mark.parametrize("status", [200, 301])
def test_reachable_head_statuses(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status]),
    )
    assert result.outcome == "reachable"
    assert result.http_status == status


@pytest.mark.parametrize("status", [404, 410, 451])
def test_definitive_negative_statuses_are_dead(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status]),
    )
    assert result.outcome == "dead"
    assert result.http_status == status


@pytest.mark.parametrize("status", [403, 500])
def test_non_definitive_statuses_are_unknown(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status, status]),
    )
    assert result.outcome == "unknown"
    assert result.http_status == status


def test_head_405_falls_back_to_ranged_get(public_dns) -> None:
    opener = FakeOpener([405, 206])
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=opener,
    )
    assert result.outcome == "reachable"
    assert [request.get_method() for request in opener.requests] == ["HEAD", "GET"]
    assert opener.requests[1].get_header("Range") == "bytes=0-0"


def test_timeout_is_unknown(public_dns) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([TimeoutError()]),
    )
    assert result.outcome == "unknown"
    assert result.reason == "TimeoutError"


def test_dns_failure_is_unknown(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(url_probe.socket, "getaddrinfo", fail)
    result = probe_url("https://example.com/a", settings=_settings())
    assert result.outcome == "unknown"
    assert result.reason == "gaierror"


@pytest.mark.parametrize(
    "url,address",
    [
        ("http://127.0.0.1:8000/", "127.0.0.1"),
        ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
    ],
)
def test_non_public_hosts_are_dead(monkeypatch, url: str, address: str) -> None:
    monkeypatch.setattr(
        url_probe.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))
        ],
    )
    result = probe_url(url, settings=_settings())
    assert result.outcome == "dead"
    assert result.reason == "non-public host"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a"])
def test_unsupported_schemes_are_dead(url: str) -> None:
    result = probe_url(url, settings=_settings())
    assert result.outcome == "dead"
    assert result.reason == "unsupported URL scheme"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("http://127.0.0.1:10809", {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}),
        ("none", {}),
    ],
)
def test_opener_uses_only_the_configured_proxy(
    public_dns,
    monkeypatch,
    configured: str,
    expected: dict[str, str],
) -> None:
    captured: list[ProxyHandler] = []
    fake = FakeOpener([200])

    def build(handler: ProxyHandler):
        captured.append(handler)
        return fake

    monkeypatch.setattr(url_probe, "build_opener", build)
    result = probe_url(
        "https://example.com/a",
        settings=_settings(http_proxy=configured),
    )
    assert result.outcome == "reachable"
    assert captured[0].proxies == expected
''',
)

write(
    "tests/test_web_search_cache.py",
    '''from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from thesisound.config import Settings
from thesisound.domain import SearchQuery, SourceRole
from thesisound.ports import RawSearchResult
from thesisound.services.web_search_cache import WebSearchCache


def _settings(tmp_path: Path, *, model: str = "model-a") -> Settings:
    return Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        model_fast=model,
        http_proxy="none",
    )


def _query(value: str = "ethics") -> SearchQuery:
    return SearchQuery(
        query=value,
        provider="web",
        source_role=SourceRole.REFERENCE,
        language="fa",
        purpose="test",
        priority=3,
    )


def _results() -> list[RawSearchResult]:
    return [
        RawSearchResult(
            provider="fake",
            title="Result",
            url="https://example.com/result",
            snippet_or_abstract="snippet",
        )
    ]


def test_miss_save_hit_round_trip(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()

    assert cache.load(project_id, query) is None
    cache.save(query, _results())
    assert cache.load(project_id, query) == _results()


def test_expired_entry_is_a_miss(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()
    cache.save(query, _results())
    frozen_clock.advance((settings.web_search_cache_ttl_hours + 1) * 3600)

    assert cache.load(project_id, query) is None


def test_corrupt_json_is_a_miss(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    query = _query()
    path = cache.path_for(query)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"truncated":', encoding="utf-8")

    assert cache.load(uuid4(), query) is None


def test_query_and_model_are_part_of_the_key(tmp_path: Path, frozen_clock) -> None:
    settings_a = _settings(tmp_path, model="model-a")
    cache_a = WebSearchCache(settings_a.workspace_root, settings_a, now=frozen_clock.now)
    cache_a.save(_query("one"), _results())

    assert cache_a.load(uuid4(), _query("two")) is None
    settings_b = _settings(tmp_path, model="model-b")
    cache_b = WebSearchCache(settings_b.workspace_root, settings_b, now=frozen_clock.now)
    assert cache_b.load(uuid4(), _query("one")) is None
    assert cache_a.path_for(_query("one")) != cache_b.path_for(_query("one"))


def test_cache_lookup_events_report_hit_and_miss(
    tmp_path: Path,
    frozen_clock,
    recording_tracer,
) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()
    cache.load(project_id, query)
    cache.save(query, _results())
    cache.load(project_id, query)

    events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "web_search"
    ]
    assert [event.attributes["result"] for event in events] == ["miss", "hit"]
''',
)

# Keep existing capture tests offline, add probe/cache integration coverage.
path = "tests/test_web_source_discovery.py"
content = read(path)
content = content.replace(
    "        ui_demo_mode=False,\n",
    "        ui_demo_mode=False,\n        url_probe_enabled=False,\n",
    1,
)
content = content.replace(
    "    def __init__(self, capture: WebSourceCaptureDraft) -> None:\n        self.capture = capture\n",
    "    def __init__(self, capture: WebSourceCaptureDraft) -> None:\n"
    "        self.capture = capture\n"
    "        self.calls = 0\n",
    1,
)
content = content.replace(
    "        assert output_type is WebSourceCaptureDraft\n",
    "        self.calls += 1\n        assert output_type is WebSourceCaptureDraft\n",
    1,
)
if "UrlProbeResult" not in content:
    content = content.replace(
        "from thesisound.ports import RawSearchResult\n",
        "from thesisound.ports import RawSearchResult\n"
        "from thesisound.services.url_probe import UrlProbeResult\n",
        1,
    )
if "test_dead_url_is_blocked_before_any_model_call" not in content:
    content += '''


def test_dead_url_is_blocked_before_any_model_call(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.url_probe_enabled = True
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    runner = FakeRunner(_capture(full=True))
    monkeypatch.setattr(
        source_discovery,
        "probe_url",
        lambda *_args, **_kwargs: UrlProbeResult(
            "https://example.com/dead", "dead", 404, "HTTP 404"
        ),
    )
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "ModelRunner", lambda *_, **__: runner)

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="Dead",
            url="https://example.com/dead",
        ),
    )

    assert manifest.status == UiSourceStatus.BLOCKED
    assert runner.calls == 0


def test_unknown_probe_outcome_still_attempts_capture(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.url_probe_enabled = True
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    runner = FakeRunner(_capture(full=True))
    monkeypatch.setattr(
        source_discovery,
        "probe_url",
        lambda *_args, **_kwargs: UrlProbeResult(
            "https://example.com/article", "unknown", None, "TimeoutError"
        ),
    )
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "ModelRunner", lambda *_, **__: runner)

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="Article",
            url="https://example.com/article",
        ),
    )

    assert manifest.status == UiSourceStatus.READY
    assert runner.calls == 1


def test_repeated_identical_search_uses_the_cache(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()

    class CountingSearchPort:
        calls = 0

        def __init__(self, *_: object, **__: object) -> None:
            pass

        def search(self, _query):
            type(self).calls += 1
            return [
                RawSearchResult(
                    provider="fake",
                    title="Cached",
                    url="https://example.com/cached",
                )
            ]

    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "GeminiWebSearchPort", CountingSearchPort)
    service = WebSourceDiscoveryService(settings, workspace)

    first = service.search(project, "اخلاق")
    second = service.search(project, "اخلاق")

    assert first == second
    assert CountingSearchPort.calls == 1
'''
write(path, content)
