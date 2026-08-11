from __future__ import annotations

import hashlib
import re
from uuid import UUID, uuid4

from pydantic import HttpUrl, ValidationError

from thesisound import tracing
from thesisound.adapters.fetch.trafilatura import UrlFetchError, fetch_and_extract_url
from thesisound.config import Settings
from thesisound.pipeline import WorkspaceStore
from thesisound.services.url_probe import probe_url
from thesisound.web.source_ingestion import ingest_uploaded_source
from thesisound.web.source_manifest import UiSourceManifest, UiSourceStatus


class UrlSourceImportService:
    """Import a user-pasted URL as a Markdown source via Trafilatura."""

    def __init__(self, settings: Settings, workspace: WorkspaceStore) -> None:
        self.settings = settings
        self.workspace = workspace

    def import_url(self, project_id: UUID, url: str) -> UiSourceManifest:
        if not self.settings.url_source_fetch_enabled:
            raise ValueError(
                "افزودن منبع از نشانی وب فعلاً در دسترس نیست. فایل منبع را بارگذاری کنید."
            )
        canonical = normalize_source_url(url)

        if self.settings.url_probe_enabled:
            probe = probe_url(canonical, settings=self.settings)
            if probe.outcome == "dead":
                tracing.event(
                    "source.probe_blocked",
                    component="source",
                    project_id=project_id,
                    level="warn",
                    reason=probe.reason,
                    http_status=probe.http_status,
                )
                return UiSourceManifest(
                    source_id=uuid4(),
                    filename=_url_filename(canonical),
                    display_title=canonical,
                    content_type="text/markdown",
                    size_bytes=0,
                    status=UiSourceStatus.BLOCKED,
                    issue_summary=(
                        "نشانی منبع به‌طور قطعی در دسترس نیست و پیش از استخراج متن "
                        "مسدود شد."
                    ),
                    origin="url_fetch",
                    canonical_url=canonical,
                    retrieval_scope="unavailable",
                    quality_issues=[probe.reason],
                )

        source_id = uuid4()
        try:
            fetched = fetch_and_extract_url(canonical, settings=self.settings)
        except UrlFetchError as error:
            tracing.event(
                "source.url_fetch_failed",
                component="source",
                project_id=project_id,
                level="warn",
                reason=str(error),
            )
            return UiSourceManifest(
                source_id=source_id,
                filename=_url_filename(canonical),
                display_title=canonical,
                content_type="text/markdown",
                size_bytes=0,
                status=UiSourceStatus.BLOCKED,
                issue_summary=(
                    "متن منبع از این نشانی بازیابی نشد؛ صفحه خالی، محافظت‌شده، "
                    "یا غیرقابل‌استخراج بود."
                ),
                origin="url_fetch",
                canonical_url=canonical,
                retrieval_scope="unavailable",
                quality_issues=[str(error)],
            )

        if fetched.text_characters < self.settings.url_fetch_min_characters:
            return UiSourceManifest(
                source_id=source_id,
                filename=_url_filename(fetched.title),
                display_title=fetched.title,
                content_type="text/markdown",
                size_bytes=0,
                status=UiSourceStatus.BLOCKED,
                issue_summary=(
                    "متن بازیابی‌شده کوتاه‌تر از حد لازم برای استناد قابل‌اتکا است."
                ),
                origin="url_fetch",
                canonical_url=canonical,
                retrieval_scope="partial_text",
                quality_issues=[
                    f"extracted {fetched.text_characters} characters "
                    f"(minimum {self.settings.url_fetch_min_characters})"
                ],
            )

        upload_root = (
            self.workspace.project_dir(project_id) / "uploads" / "web" / str(source_id)
        )
        upload_root.mkdir(parents=True, exist_ok=True)
        filename = _url_filename(fetched.title)
        path = upload_root / filename
        path.write_text(fetched.markdown, encoding="utf-8")
        size_bytes = path.stat().st_size
        artifact_root = (
            self.settings.ensure_ingestion_artifact_root()
            / str(project_id)
            / str(source_id)
        )
        manifest = ingest_uploaded_source(
            path,
            source_id=source_id,
            filename=filename,
            content_type="text/markdown",
            size_bytes=size_bytes,
            settings=self.settings,
            artifact_root=artifact_root,
        )
        manifest.display_title = fetched.title
        manifest.origin = "url_fetch"
        manifest.canonical_url = canonical
        manifest.retrieval_scope = "full_text"
        if manifest.status == UiSourceStatus.READY:
            manifest.selected = True
        return manifest


def normalize_source_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("نشانی وب خالی است.")
    try:
        return str(HttpUrl(cleaned))
    except ValidationError as error:
        raise ValueError("نشانی وب معتبر نیست.") from error


def _url_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u0600-\u06ff_-]+", "-", title).strip("-")
    if not slug:
        slug = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"{slug[:100]}.url.md"
