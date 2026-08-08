from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from thesisound.config import Settings
from thesisound.domain import (
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceExtraction,
    EvidenceItem,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.script import ScriptCheckReport, ScriptPipelineManifest, VerificationDraft
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunStore,
)
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRun, ScriptBuildRunStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import BlockEvidenceExtraction
from thesisound.web.app import create_app
from thesisound.web.source_manifest import UiSourceManifestStore

ROOT = Path(__file__).parents[1]
THEMES = ("cobalt", "wood", "olive")
MODES = ("simple", "operator")


def _settings(output: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=output / "runtime" / "workspaces",
        ingestion_artifact_root=output / "runtime" / "artifacts",
        web_session_secret="visual-qa-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="0912000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=1,
        ui_demo_mode=False,
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _static_html(html: str) -> str:
    return (
        html.replace("http://testserver/static/app.css", "/static/app.css")
        .replace("http://testserver/static/app.js", "/static/app.js")
        .replace("https://unpkg.com/htmx.org@2.0.4", "/static/empty.js")
    )


def _save_page(output: Path, name: str, response) -> None:
    if response.status_code != 200:
        raise RuntimeError(f"{name} returned {response.status_code}")
    destination = output / "implementation" / f"{name}.html"
    destination.write_text(_static_html(response.text), encoding="utf-8")


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "0912000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    response = client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )
    if response.status_code != 200:
        raise RuntimeError("visual QA login failed")


def _brief() -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
        topic_type=TopicType.CONCEPT,
        central_question="چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
        audience="دانشجوی علوم انسانی",
        prior_knowledge="introductory",
        target_duration_minutes=20,
        learning_objectives=["فهم نسبت عصبیت، دولت و زوال سیاسی"],
    )


def _episode_plan() -> EpisodePlan:
    return EpisodePlan(
        title="از عصبیت تا دولت",
        listener_outcome="فهم منطق پیدایش و فرسایش دولت در اندیشه ابن‌خلدون",
        estimated_duration_minutes=18,
        segments=[
            EpisodeSegment(
                segment_id="seg-1",
                title="مسئله دولت",
                purpose="تعریف پرسش و زمینه تاریخی",
                estimated_minutes=6,
                claim_ids=["claim-1"],
                key_question="دولت چگونه از پیوند اجتماعی پدید می‌آید؟",
                speaker_dynamic="explanation",
            ),
            EpisodeSegment(
                segment_id="seg-2",
                title="عصبیت و قدرت",
                purpose="توضیح سازوکار تبدیل عصبیت به فرمانروایی",
                estimated_minutes=7,
                claim_ids=["claim-1"],
                key_question="چرا همان نیروی مؤسس به‌تدریج فرسوده می‌شود؟",
                speaker_dynamic="analysis",
            ),
            EpisodeSegment(
                segment_id="seg-3",
                title="اهمیت امروز",
                purpose="تفکیک استفاده تحلیلی از قیاس ساده‌انگارانه",
                estimated_minutes=5,
                claim_ids=["claim-1"],
                key_question="این مدل امروز چه چیزی را روشن می‌کند؟",
                speaker_dynamic="synthesis",
            ),
        ],
    )


def _seed_verified_script(settings: Settings) -> Project:
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = Project(
        raw_input="دولت نزد ابن‌خلدون",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=_brief(),
        episode_plan=_episode_plan(),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="مقدمه ابن‌خلدون",
                role=SourceRole.PRIMARY,
                source_type="book",
                origin="fixture",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
        script=Script(
            title="از عصبیت تا دولت",
            turns=[
                ScriptTurn(
                    turn_id="seg-1-turn-001",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa=(
                        "ابن‌خلدون دولت را صرفاً یک دستگاه اداری نمی‌بیند؛ "
                        "آن را برآمده از نیروی هم‌بستگی و توان غلبه می‌داند."
                    ),
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                ),
                ScriptTurn(
                    turn_id="seg-1-turn-002",
                    segment_id="seg-1",
                    speaker="B",
                    spoken_text_fa=(
                        "اما این توضیح یک چرخه مکانیکی نیست؛ باید زمینه تاریخی "
                        "و تفاوت شکل‌های اقتدار را هم در نظر گرفت."
                    ),
                    editorial_only=True,
                ),
            ],
        ),
    )
    workspace.save_project(project)
    approval = EpisodePlanApproval(
        project_id=project.project_id,
        plan_hash=episode_plan_hash(project.episode_plan),
        approved_by="0912000000",
    )
    EpisodePlanApprovalStore(settings.workspace_root).save(approval)
    ScriptBuildRunStore(settings.workspace_root).save(
        ScriptBuildRun(
            project_id=project.project_id,
            approved_plan_hash=approval.plan_hash,
            approved_by=approval.approved_by,
            status="succeeded",
            stage="complete",
        )
    )
    script_store = ScriptArtifactStore(settings.workspace_root)
    script_store.save_script(project.project_id, project.script)
    script_store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=1940,
            estimated_minutes=17.6,
            substantive_turn_count=1,
        )
    )
    script_store.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    script_store.save_manifest(
        ScriptPipelineManifest(project_id=project.project_id, status="verified")
    )
    SourceArtifactStore(settings.workspace_root).save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[
                        EvidenceItem(
                            evidence_id="evidence-1",
                            source_id=source_id,
                            block_id="block-1",
                            claim="دولت از عصبیت و توان غلبه برمی‌آید.",
                            claim_type=ClaimType.AUTHOR_POSITION,
                            supporting_excerpt=(
                                "فرمانروایی و دولت تنها با غلبه و عصبیت حاصل می‌شود."
                            ),
                            locator=Locator(page_start=121, page_end=121),
                            support_kind="direct",
                            confidence=0.94,
                        )
                    ],
                ),
            )
        ],
    )
    return project


def prepare(output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    (output / "implementation").mkdir(parents=True)
    (output / "source").mkdir(parents=True)
    (output / "static").mkdir(parents=True)
    (output / "output").mkdir(parents=True)

    shutil.copy2(ROOT / "src/thesisound/web/static/app.css", output / "static/app.css")
    shutil.copy2(ROOT / "src/thesisound/web/static/app.js", output / "static/app.js")
    (output / "static/empty.js").write_text("", encoding="utf-8")
    shutil.copy2(
        ROOT / "docs/ui-refactor/Thesisound UI v2.dc.html",
        output / "source/artifact.html",
    )
    shutil.copy2(ROOT / "docs/ui-refactor/support.js", output / "source/support.js")

    settings = _settings(output)
    workspace = WorkspaceStore(settings.workspace_root)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )

    pages: list[str] = []
    with TestClient(app) as client:
        _save_page(output, "login", client.get("/login"))
        pages.append("login")

        login_page = client.get("/login")
        client.post(
            "/login/request-code",
            data={
                "phone": "0912000000",
                "csrf_token": _csrf(login_page.text),
                "next_path": "/projects",
            },
        )
        _save_page(output, "verify", client.get("/login/verify"))
        pages.append("verify")
        verify_page = client.get("/login/verify")
        client.post(
            "/login/verify",
            data={"code": "999999", "csrf_token": _csrf(verify_page.text)},
        )

        _save_page(output, "projects-empty", client.get("/projects"))
        _save_page(output, "new-project", client.get("/projects/new"))
        pages.extend(("projects-empty", "new-project"))

        new_page = client.get("/projects/new")
        created = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
                "audience": "دانشجوی علوم انسانی",
                "prior_knowledge": "introductory",
                "duration": "20",
                "mode": "explanatory",
            },
            follow_redirects=False,
        )
        project_id = created.headers["location"].split("/")[2]
        _save_page(output, "brief", client.get(created.headers["location"]))
        _save_page(output, "overview", client.get(f"/projects/{project_id}"))
        pages.extend(("brief", "overview"))

        brief_page = client.get(created.headers["location"])
        client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
                "must_include": "عصبیت\nچرخه پیدایش و زوال دولت",
                "exclusions": "زندگی‌نامه تفصیلی",
                "action": "confirm",
            },
        )
        source_page = client.get(f"/projects/{project_id}/sources")
        source_text = (
            "ابن‌خلدون دولت را با عصبیت، غلبه و دگرگونی شیوه زندگی توضیح می‌دهد. "
            * 30
        ).encode()
        client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(source_page.text)},
            files={"source_file": ("مقدمه-ابن-خلدون.txt", source_text, "text/plain")},
        )
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        source = manifest_store.load()[0]
        source_page = client.get(f"/projects/{project_id}/sources")
        match = re.search(r'data-source-id="([0-9a-f-]{36})"', source_page.text)
        if match is None:
            raise RuntimeError("visual QA source row was not rendered")
        client.post(
            f"/projects/{project_id}/sources/{match.group(1)}/toggle",
            data={"csrf_token": _csrf(source_page.text)},
        )
        source_page = client.get(f"/projects/{project_id}/sources")
        if not source.selected and not manifest_store.load()[0].selected:
            raise RuntimeError("visual QA source selection failed")
        _save_page(output, "sources", source_page)
        pages.append("sources")

        client.post(
            f"/projects/{project_id}/corpus/confirm",
            data={"csrf_token": _csrf(source_page.text)},
        )
        _save_page(output, "processing", client.get(f"/projects/{project_id}/processing"))
        pages.append("processing")

        blocked_project = Project(
            raw_input="دولت نزد ابن‌خلدون",
            state=ProjectState.EPISODE_PLANNING,
            brief=_brief(),
        )
        workspace.save_project(blocked_project)
        EpisodePlanningRunStore(settings.workspace_root).save(
            EpisodePlanningRun(
                project_id=blocked_project.project_id,
                status="blocked",
                stage="blocked",
                target_duration_minutes=20,
                max_supported_minutes=12,
                material_gaps=[
                    "زمینه تاریخی شکل‌گیری دولت‌های مورد بحث کافی نیست.",
                    "برای نقدهای معاصر یک منبع مستقل لازم است.",
                ],
                last_error="coverage below requested duration",
            )
        )
        _save_page(
            output,
            "episode",
            client.get(f"/projects/{blocked_project.project_id}/episode"),
        )
        pages.append("episode")

        script_project = _seed_verified_script(settings)
        _save_page(
            output,
            "script",
            client.get(f"/projects/{script_project.project_id}/script"),
        )
        _save_page(
            output,
            "audio",
            client.get(f"/projects/{script_project.project_id}/audio"),
        )
        pages.extend(("script", "audio"))

        _save_page(output, "system-check", client.get("/system-check?scope=full"))
        _save_page(output, "projects", client.get("/projects"))
        pages.extend(("system-check", "projects"))

    (output / "pages.json").write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _contact_sheet(paths: list[Path], destination: Path, *, columns: int = 3) -> None:
    if not paths:
        return
    cell_width = 480
    cell_height = 650
    label_height = 28
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell_width - 16, cell_height - label_height - 16))
        x = (index % columns) * cell_width + (cell_width - image.width) // 2
        y = (index // columns) * cell_height + label_height
        sheet.paste(image, (x, y))
        draw.text(
            ((index % columns) * cell_width + 8, (index // columns) * cell_height + 6),
            path.stem,
            fill="black",
        )
    sheet.save(destination, quality=88)


async def capture(output: Path, base_url: str) -> None:
    from playwright.async_api import async_playwright

    pages = json.loads((output / "pages.json").read_text(encoding="utf-8"))["pages"]
    screenshots = output / "output" / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    console_events: list[dict[str, str]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=1,
        )
        page.on(
            "console",
            lambda message: console_events.append(
                {"type": message.type, "text": message.text}
            )
            if message.type in {"error", "warning"}
            else None,
        )
        page.on(
            "pageerror",
            lambda error: console_events.append(
                {"type": "pageerror", "text": str(error)}
            ),
        )

        for name in pages:
            for theme in THEMES:
                for mode in MODES:
                    await page.goto(
                        f"{base_url}/implementation/{name}.html",
                        wait_until="networkidle",
                    )
                    await page.evaluate(
                        """([theme, mode]) => {
                            document.documentElement.dataset.theme = theme;
                            document.documentElement.dataset.mode = mode;
                        }""",
                        [theme, mode],
                    )
                    await page.evaluate("document.fonts.ready")
                    await page.screenshot(
                        path=screenshots / f"impl-{theme}-{mode}-{name}.png",
                        full_page=True,
                    )

        mobile = await browser.new_page(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
        )
        for name in pages:
            await mobile.goto(
                f"{base_url}/implementation/{name}.html",
                wait_until="networkidle",
            )
            await mobile.evaluate(
                """() => {
                    document.documentElement.dataset.theme = 'cobalt';
                    document.documentElement.dataset.mode = 'simple';
                }"""
            )
            await mobile.evaluate("document.fonts.ready")
            await mobile.screenshot(
                path=screenshots / f"mobile-cobalt-simple-{name}.png",
                full_page=True,
            )
        await mobile.close()

        await page.goto(f"{base_url}/source/artifact.html", wait_until="networkidle")
        source_screens = page.locator("[data-screen-label]")
        source_count = await source_screens.count()
        source_labels: list[str] = []
        for theme in THEMES:
            await page.evaluate(
                "theme => document.querySelectorAll('[data-theme]').forEach("
                "node => node.setAttribute('data-theme', theme))",
                theme,
            )
            await page.evaluate("document.fonts.ready")
            for index in range(source_count):
                screen = source_screens.nth(index)
                label = (await screen.get_attribute("data-screen-label")) or str(index + 1)
                safe_label = re.sub(r"[^0-9A-Za-z_-]+", "-", label).strip("-")
                if theme == "cobalt":
                    source_labels.append(label)
                await screen.screenshot(
                    path=screenshots / f"source-{theme}-{index + 1:02d}-{safe_label}.png"
                )

        await page.goto(
            f"{base_url}/implementation/projects.html",
            wait_until="networkidle",
        )
        await page.click('[data-theme-value="wood"]')
        await page.click('[data-mode-value="operator"]')
        switched = await page.evaluate(
            """() => ({
                theme: document.documentElement.dataset.theme,
                mode: document.documentElement.dataset.mode
            })"""
        )
        if switched != {"theme": "wood", "mode": "operator"}:
            raise RuntimeError(f"theme/mode interaction failed: {switched}")

        await browser.close()

    manifest = {
        "viewport": {"desktop": [1440, 1000], "mobile": [390, 844]},
        "device_scale_factor": 1,
        "implementation_pages": pages,
        "source_screen_labels": source_labels,
        "themes": list(THEMES),
        "modes": list(MODES),
        "interaction": switched,
        "console_events": console_events,
    }
    (output / "output" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for theme in THEMES:
        source_paths = sorted(screenshots.glob(f"source-{theme}-*.png"))
        _contact_sheet(
            source_paths,
            output / "output" / f"source-{theme}-contact.jpg",
        )
        for mode in MODES:
            implementation_paths = [
                screenshots / f"impl-{theme}-{mode}-{name}.png" for name in pages
            ]
            _contact_sheet(
                implementation_paths,
                output / "output" / f"implementation-{theme}-{mode}-contact.jpg",
            )
    mobile_paths = [
        screenshots / f"mobile-cobalt-simple-{name}.png" for name in pages
    ]
    _contact_sheet(
        mobile_paths,
        output / "output" / "mobile-cobalt-simple-contact.jpg",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "capture"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
    else:
        asyncio.run(capture(args.output, args.base_url))


if __name__ == "__main__":
    main()
