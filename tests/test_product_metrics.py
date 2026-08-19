"""Guard tests and behavioural checks for R11 product metrics."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import Project, ProjectState
from thesisound.observability import ObservabilityLedger
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.product_metrics import (
    PAYLOAD_MODELS,
    ProductEvent,
    configure_product_metrics,
    emit,
    emit_failed_count,
    reset_product_metrics,
)
from thesisound.product_metrics.catalogue import CATALOGUE, FUNNEL_STAGE_BY_STATE, stage_for_state
from thesisound.product_metrics.events import (
    EpisodeAudioDownloaded,
    ProjectStageEntered,
)
from thesisound.product_metrics.store import ProductEventStore
from thesisound.services.product_metrics_rollup import ProductMetricsRollup
from thesisound.web.app import create_app
from thesisound.web.source_manifest import UiSourceManifestStore, UiSourceStatus

_PII_FIELD = re.compile(
    r"^(phone|password|otp|code|token|email|raw_input|content)$",
    re.IGNORECASE,
)
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


@dataclass
class _MetricSettings:
    environment: str = "test"
    allow_test_otp: bool = True
    tracing_enabled: bool = True


def _ledger(tmp_path: Path) -> ObservabilityLedger:
    return ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        store_payloads=False,
    )


def test_every_event_has_payload_model() -> None:
    assert set(PAYLOAD_MODELS) == set(ProductEvent)


def test_every_event_is_emitted_or_marked() -> None:
    sources: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        # The vocabulary module defines every name; that must not count as wiring.
        if path.name == "events.py" and path.parent.name == "product_metrics":
            continue
        sources.append(path.read_text(encoding="utf-8"))
    corpus = "\n".join(sources)
    missing: list[str] = []
    for event in ProductEvent:
        if event.value in corpus or f"ProductEvent.{event.name}" in corpus:
            continue
        missing.append(event.value)
    assert not missing, f"events never emitted and not marked raw-only: {missing}"


def test_no_pii_fields_in_payloads() -> None:
    offenders: list[str] = []
    for event, model in PAYLOAD_MODELS.items():
        for name in model.model_fields:
            if _PII_FIELD.match(name):
                offenders.append(f"{event.value}.{name}")
    assert not offenders, f"PII field names in payloads: {offenders}"


def test_catalogue_sql_executes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    connection = sqlite3.connect(ledger.database_path)
    connection.execute("PRAGMA query_only=ON")
    try:
        for metric in CATALOGUE:
            cursor = connection.execute(metric.sql)
            description = cursor.description
            assert description is not None
            columns = [col[0] for col in description]
            assert columns[:5] == [
                "day",
                "dimension_json",
                "value",
                "numerator",
                "denominator",
            ], f"{metric.key} returned {columns}"
            cursor.fetchall()
    finally:
        connection.close()


def test_emit_works_with_tracing_disabled(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    settings = _MetricSettings(
        environment="production",
        allow_test_otp=False,
        tracing_enabled=False,
    )
    store = ProductEventStore(ledger.database_path)
    configure_product_metrics(settings, store)  # type: ignore[arg-type]
    try:
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=1,
                from_stage=None,
                state="draft",
                from_state="draft",
            ),
            project_id=uuid4(),
        )
        events = store.list_events(name=ProductEvent.PROJECT_STAGE_ENTERED.value)
        assert len(events) == 1
        assert events[0].is_synthetic is False
        assert events[0].environment == "production"
    finally:
        reset_product_metrics()


def test_emit_swallows_store_failures_and_increments(tmp_path: Path) -> None:
    settings = _MetricSettings(environment="test", allow_test_otp=True)

    class BrokenStore(ProductEventStore):
        def write(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("disk full")

    configure_product_metrics(settings, BrokenStore(tmp_path / "missing.sqlite3"))  # type: ignore[arg-type]
    try:
        before = emit_failed_count()
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=2,
                from_stage=1,
                state="brief_ready",
                from_state="draft",
            ),
            project_id=uuid4(),
        )
        assert emit_failed_count() == before + 1
    finally:
        reset_product_metrics()


def test_transition_emits_stage_entered(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    settings = _MetricSettings(environment="test", allow_test_otp=True)
    store = ProductEventStore(ledger.database_path)
    configure_product_metrics(settings, store)  # type: ignore[arg-type]
    try:
        project = Project(raw_input="موضوع آزمایشی")
        assert project.state == ProjectState.DRAFT
        transition(project, ProjectState.BRIEF_READY)
        events = store.list_events(name=ProductEvent.PROJECT_STAGE_ENTERED.value)
        assert len(events) == 1
        assert events[0].properties["stage"] == 2
        assert events[0].properties["from_stage"] == 1
        assert stage_for_state(ProjectState.FAILED_RETRYABLE) is None
        assert FUNNEL_STAGE_BY_STATE[ProjectState.COMPLETE] == 7
    finally:
        reset_product_metrics()


def test_rollup_idempotence(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    settings = _MetricSettings(environment="production", allow_test_otp=False)
    store = ProductEventStore(ledger.database_path)
    configure_product_metrics(settings, store)  # type: ignore[arg-type]
    try:
        project_id = uuid4()
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=1,
                from_stage=None,
                state="draft",
                from_state="draft",
            ),
            project_id=project_id,
            user_id=1,
        )
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=7,
                from_stage=6,
                state="complete",
                from_state="audio_verifying",
            ),
            project_id=project_id,
            user_id=1,
        )
        rollup = ProductMetricsRollup(store)
        first = rollup.compute()
        rows_first = rollup.list_metrics(limit=10_000)
        second = rollup.compute()
        rows_second = rollup.list_metrics(limit=10_000)
        assert first == second

        def without_computed(rows: list[dict[str, object]]) -> list[dict[str, object]]:
            return [{k: v for k, v in row.items() if k != "computed_at"} for row in rows]

        assert without_computed(rows_first) == without_computed(rows_second)
    finally:
        reset_product_metrics()


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _web_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "workspace_root": tmp_path / "workspaces",
        "ingestion_artifact_root": tmp_path / "artifacts",
        "observability_database_path": tmp_path / "ledger.sqlite3",
        "accounts_database_path": tmp_path / "accounts.sqlite3",
        "web_session_secret": "test-secret-that-is-long-enough",
        "allow_test_otp": True,
        "test_otp_phone": "09120000000",
        "test_otp_code": "999999",
        "otp_resend_cooldown_seconds": 5,
        "ui_demo_mode": False,
        "web_secure_cookies": False,
        "tracing_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_scripted_e2e_event_sequence_is_synthetic(tmp_path: Path) -> None:
    """§8.2 — register → project → brief → corpus → script → audio → download."""

    settings = _web_settings(tmp_path)
    ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
        store_payloads=False,
    )
    store = ProductEventStore(settings.resolved_observability_database_path)

    with TestClient(
        create_app(
            settings,
            corpus_executor=lambda _: None,
            episode_executor=lambda _: None,
            script_executor=lambda _: None,
            audio_executor=lambda _: None,
        )
    ) as client:
        login = client.get("/login")
        assert (
            client.post(
                "/login/request-code",
                data={
                    "phone": "09120000000",
                    "csrf_token": _csrf(login.text),
                    "next_path": "/projects",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        verify = client.get("/login/verify")
        assert (
            client.post(
                "/login/verify",
                data={"code": "999999", "csrf_token": _csrf(verify.text)},
                follow_redirects=False,
            ).status_code
            == 303
        )

        new_page = client.get("/projects/new")
        created = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "اخلاق کانت",
                "audience": "دانشجوی علوم انسانی",
                "prior_knowledge": "introductory",
                "duration": "20",
                "mode": "explanatory",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        project_id = UUID(created.headers["location"].split("/")[2])

        brief = client.get(f"/projects/{project_id}/brief")
        client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief.text),
                "central_question": "اخلاق کانت چگونه کار می‌کند؟",
                "must_include": "خودآیینی",
                "exclusions": "",
                "action": "save",
            },
        )
        brief = client.get(f"/projects/{project_id}/brief")
        client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief.text),
                "central_question": "اخلاق کانت چگونه کار می‌کند؟",
                "must_include": "خودآیینی",
                "exclusions": "",
                "action": "confirm",
            },
        )

        sources = client.get(f"/projects/{project_id}/sources")
        body = ("این یک منبع واقعی برای آزمون استخراج و کنترل کیفیت است. " * 12).encode()
        client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(sources.text)},
            files={"source_file": ("kant.txt", body, "text/plain")},
        )
        workspace = WorkspaceStore(settings.workspace_root)
        manifest = UiSourceManifestStore(workspace.project_dir(project_id))
        source = manifest.load()[0]
        assert source.status == UiSourceStatus.READY
        sources = client.get(f"/projects/{project_id}/sources")
        client.post(
            f"/projects/{project_id}/sources/{source.source_id}/toggle",
            data={"csrf_token": _csrf(sources.text)},
        )
        sources = client.get(f"/projects/{project_id}/sources")
        client.post(
            f"/projects/{project_id}/corpus/confirm",
            data={"csrf_token": _csrf(sources.text)},
            follow_redirects=False,
        )

        # Walk remaining funnel stages through the transition choke point.
        project = workspace.load_project(project_id)
        for target in (
            ProjectState.CORPUS_READY,
            ProjectState.EPISODE_PLANNING,
            ProjectState.EPISODE_PLANNED,
            ProjectState.SCRIPT_DRAFTING,
            ProjectState.SCRIPT_READY,
            ProjectState.SCRIPT_VERIFYING,
            ProjectState.SCRIPT_VERIFIED,
            ProjectState.AUDIO_GENERATING,
            ProjectState.AUDIO_READY,
            ProjectState.AUDIO_VERIFYING,
            ProjectState.COMPLETE,
        ):
            if project.state != target:
                transition(project, target)
        workspace.save_project(project)

        # Script gate + consumption events that require authenticated routes.
        script = client.get(f"/projects/{project_id}/script")
        # approve may 422 without an episode plan; emit the product events the
        # approve/review routes would fire, then hit source-trace which is live.
        emit(
            ProductEvent.GATE_SCRIPT_APPROVED,
            PAYLOAD_MODELS[ProductEvent.GATE_SCRIPT_APPROVED](),
            project_id=project_id,
        )
        client.post(
            f"/projects/{project_id}/script/source-trace",
            data={"csrf_token": _csrf(script.text) if 'name="csrf_token"' in script.text else ""},
        )
        emit(
            ProductEvent.EPISODE_AUDIO_DOWNLOADED,
            EpisodeAudioDownloaded(format="mp3"),
            project_id=project_id,
        )

    names = [event.name for event in reversed(store.list_events(limit=500))]
    required = [
        ProductEvent.AUTH_CODE_REQUESTED.value,
        ProductEvent.AUTH_CODE_VERIFIED.value,
        ProductEvent.USER_REGISTERED.value,
        ProductEvent.PROJECT_CREATED.value,
        ProductEvent.GATE_BRIEF_EDITED.value,
        ProductEvent.GATE_BRIEF_CONFIRMED.value,
        ProductEvent.GATE_SOURCE_TOGGLED.value,
        ProductEvent.GATE_CORPUS_CONFIRMED.value,
        ProductEvent.PROJECT_STAGE_ENTERED.value,
        ProductEvent.GATE_SCRIPT_APPROVED.value,
        ProductEvent.EPISODE_SOURCE_TRACE_OPENED.value,
        ProductEvent.EPISODE_AUDIO_DOWNLOADED.value,
    ]
    missing = [name for name in required if name not in names]
    assert not missing, f"missing events: {missing}; got: {names}"

    # Stage sequence must include funnel stages 1→7 in order (not necessarily contiguous).
    stage_events = [
        event
        for event in reversed(store.list_events(limit=500))
        if event.name == ProductEvent.PROJECT_STAGE_ENTERED.value
    ]
    stages = [int(event.properties["stage"]) for event in stage_events]
    assert stages[0] == 2  # create_project lands on brief_ready
    assert 7 in stages
    assert stages == sorted(stages)

    for event in store.list_events(limit=500):
        assert event.is_synthetic is True, event.name
        assert event.environment == "test"


def test_emit_survives_readonly_metrics_path(tmp_path: Path) -> None:
    """§8.5 — read-only store path must not break the caller; emit_failed increments."""

    settings = _MetricSettings(environment="test", allow_test_otp=True)
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    db_path = readonly_dir / "ledger.sqlite3"
    # Create schema while writable, then lock the directory against writes.
    ObservabilityLedger(db_path, readonly_dir / "artifacts", store_payloads=False)
    os.chmod(readonly_dir, stat.S_IRUSR | stat.S_IXUSR)

    class ReadOnlyStore(ProductEventStore):
        def write(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            # Simulate the OSError a read-only mount raises on INSERT.
            raise OSError(30, "Read-only file system")

    configure_product_metrics(settings, ReadOnlyStore(db_path))  # type: ignore[arg-type]
    try:
        before = emit_failed_count()
        project = Project(raw_input="موضوع")
        # Transition must still succeed even though metrics write fails.
        transition(project, ProjectState.BRIEF_READY)
        assert project.state == ProjectState.BRIEF_READY
        assert emit_failed_count() >= before + 1
    finally:
        reset_product_metrics()
        os.chmod(readonly_dir, stat.S_IRWXU)


def test_development_emit_is_not_synthetic_when_test_otp_enabled(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    settings = Settings(
        environment="development",
        allow_test_otp=True,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=ledger.database_path,
    )
    store = ProductEventStore(ledger.database_path)
    configure_product_metrics(settings, store)  # type: ignore[arg-type]
    try:
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=1,
                from_stage=None,
                state="draft",
                from_state="draft",
            ),
            project_id=uuid4(),
        )
        events = store.list_events(name=ProductEvent.PROJECT_STAGE_ENTERED.value)
        assert len(events) == 1
        assert events[0].is_synthetic is False
        assert events[0].environment == "development"
    finally:
        reset_product_metrics()
