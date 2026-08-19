from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from thesisound.concepts import (
    ConceptCell,
    ConceptEdge,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.config import Settings
from thesisound.domain import Locator
from thesisound.services.concept_map_cache import CONCEPT_MAP_BUILDER_VERSION
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import BlockBuildReport, SourceDocumentBlock
from thesisound.web.app import create_app

_FINGERPRINT = "b" * 64


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )


def _create_project(client: TestClient) -> UUID:
    new_page = client.get("/projects/new")
    created = client.post(
        "/projects",
        data={
            "csrf_token": _csrf(new_page.text),
            "topic": "دولت نزد ابن‌خلدون",
            "audience": "دانشجوی علوم انسانی",
            "prior_knowledge": "introductory",
            "duration": "20",
            "mode": "explanatory",
        },
        follow_redirects=False,
    )
    return UUID(created.headers["location"].split("/")[2])


def _map() -> SourceConceptMap:
    return SourceConceptMap(
        source_fingerprint=_FINGERPRINT,
        builder_version=CONCEPT_MAP_BUILDER_VERSION,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="فصل یک",
                heading_path=["فصل یک"],
                block_ids=["b0001", "b0002"],
                estimated_minutes=10.0,
                detected_from="heading",
                detection_agreement="agreed",
            )
        ],
        cells=[
            ConceptCell(
                cell_key="ch00-c001",
                label_fa="مفهوم اصلی",
                kind="definition",
                tier=2,
                chapter_index=0,
                section_ids=["s001"],
                block_ids=["b0001"],
                granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
                estimated_minutes=5.0,
            ),
            ConceptCell(
                cell_key="ch00-c002",
                label_fa="استدلال وابسته",
                kind="argument",
                tier=3,
                tier_promoted=True,
                chapter_index=0,
                section_ids=["s001"],
                block_ids=["b0002"],
                granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
                estimated_minutes=6.0,
            ),
        ],
        edges=[
            ConceptEdge(
                source_key="ch00-c001",
                target_key="ch00-c002",
                type="prerequisite",
                weight=0.8,
                confidence=0.9,
                rationale_fa="بدون تعریف، استدلال کامل نیست.",
            )
        ],
        statistics=ConceptMapStatistics(
            cell_count=2,
            cells_per_tier={1: 0, 2: 1, 3: 1},
            promoted_cell_keys=["ch00-c002"],
            needs_review=["chapter detection disagreed: sample"],
        ),
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _save_map(workspace_root: Path, project_id: UUID, source_id: UUID) -> None:
    store = SourceArtifactStore(workspace_root)
    store.save_concept_map(project_id, source_id, _map())
    store.save_blocks(
        project_id,
        source_id,
        [
            SourceDocumentBlock(
                block_id="b0001",
                source_id=source_id,
                locator=Locator(),
                heading_path=["فصل یک"],
                block_type="other",
                text="تعریف مفهوم اصلی در همین پاره آمده است.",
                estimated_token_count=20,
                source_block_keys=["raw-1"],
            ),
            SourceDocumentBlock(
                block_id="b0002",
                source_id=source_id,
                locator=Locator(),
                heading_path=["فصل یک"],
                block_type="other",
                text="استدلال وابسته بر همان تعریف سوار است.",
                estimated_token_count=20,
                source_block_keys=["raw-2"],
            ),
        ],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=2,
            output_block_count=2,
        ),
    )


def test_concept_map_page_renders_tables(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_project(client)
        source_id = uuid4()
        _save_map(settings.workspace_root, project_id, source_id)
        page = client.get(f"/projects/{project_id}/sources/{source_id}/concept-map")
    assert page.status_code == 200
    assert "مفهوم اصلی" in page.text
    assert "ارتقا" in page.text
    assert "پیش‌نیاز" in page.text
    assert "بدون تعریف، استدلال کامل نیست." in page.text
    assert "تعریف مفهوم اصلی در همین پاره آمده است." in page.text
    assert "افزودن مفهوم" in page.text
    assert "تغییر اهمیت" in page.text


def test_concept_map_overlay_add_and_tier(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_project(client)
        source_id = uuid4()
        _save_map(settings.workspace_root, project_id, source_id)
        url = f"/projects/{project_id}/sources/{source_id}/concept-map"
        page = client.get(url)
        added = client.post(
            f"{url}/cells",
            data={
                "csrf_token": _csrf(page.text),
                "label_fa": "مفهوم افزوده",
                "kind": "example",
                "tier": "2",
                "chapter_index": "0",
                "block_ids": "b0001",
                "section_ids": "s001",
                "estimated_minutes": "4",
                "granularity_rationale": "نمونهٔ مستقل از متن منبع است.",
                "cell_key": "ch00-c003",
            },
            follow_redirects=True,
        )
        assert added.status_code == 200
        assert "مفهوم افزوده" in added.text
        override = client.post(
            f"{url}/tier",
            data={
                "csrf_token": _csrf(added.text),
                "cell_key": "ch00-c002",
                "tier": "1",
            },
            follow_redirects=True,
        )
        assert override.status_code == 200
        assert "مفهوم افزوده" in override.text


def test_concept_map_empty_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_project(client)
        page = client.get(f"/projects/{project_id}/sources/{uuid4()}/concept-map")
    assert page.status_code == 200
    assert "هنوز نقشه‌ای برای این منبع ساخته نشده" in page.text
