import re
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from thesisound.config import Settings
from thesisound.web.app import create_app

ROOT = Path(__file__).parents[1]
WEB_ROOT = ROOT / "src" / "thesisound" / "web"
TEMPLATES_ROOT = WEB_ROOT / "templates"
STATIC_ROOT = WEB_ROOT / "static"


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


def test_all_templates_compile() -> None:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_ROOT),
        autoescape=True,
        undefined=StrictUndefined,
    )
    environment.filters["fa_num"] = str
    environment.filters["jalali_date"] = str

    for template_name in environment.list_templates(extensions=["html"]):
        environment.get_template(template_name)


def test_theme_tokens_are_complete_and_cobalt_is_default() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")
    base = (TEMPLATES_ROOT / "base.html").read_text(encoding="utf-8")

    blocks: dict[str, set[str]] = {}
    pattern = re.compile(
        r'html\[data-theme="(?P<theme>cobalt|wood|olive|slate)"\]'
        r'(?:,\s*:root)?\s*\{(?P<body>.*?)\n\}',
        re.DOTALL,
    )
    for match in pattern.finditer(css):
        blocks[match.group("theme")] = set(
            re.findall(r"--([a-z0-9-]+)\s*:", match.group("body"))
        )

    assert set(blocks) == {"cobalt", "wood", "olive", "slate"}
    assert blocks["cobalt"] == blocks["wood"] == blocks["olive"] == blocks["slate"]
    assert 'data-theme="{{ ui_theme or \'cobalt\' }}"' in base
    assert 'data-mode="{{ ui_mode or \'simple\' }}"' in base
    assert "workflow.css" not in base


def test_workflow_navigation_is_single_six_step_contract() -> None:
    workflow = (TEMPLATES_ROOT / "projects" / "_workflow_navigation.html").read_text(
        encoding="utf-8"
    )
    project_templates = (TEMPLATES_ROOT / "projects").glob("*.html")

    for label in (
        "موضوع و هدف",
        "منابع",
        "تحلیل منابع",
        "طرح گفتار",
        "متن گفتار",
        "شنیدن",
    ):
        assert label in workflow

    for template_path in project_templates:
        if template_path.name == "_workflow_navigation.html":
            continue
        assert 'class="step-rail' not in template_path.read_text(encoding="utf-8")


def _project_with_sources(client: TestClient) -> str:
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
    brief_page = client.get(f"/projects/{project_id}/brief")
    client.post(
        f"/projects/{project_id}/brief",
        data={
            "csrf_token": _csrf(brief_page.text),
            "central_question": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
            "action": "confirm",
        },
    )
    return project_id


def test_step_rail_marks_one_current_step_and_explains_the_locked_ones(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _project_with_sources(client)
        page = client.get(f"/projects/{project_id}/sources").text

    assert page.count("workflow-step is-current") == 1
    assert page.count('aria-current="step"') == 1
    # Every locked step points at the one sentence that says why it is locked.
    assert 'id="workflow-lock-reason"' in page
    assert page.count('aria-describedby="workflow-lock-reason"') >= 1
    assert "workflow-step__lock" in page


def test_source_delete_needs_the_impact_summary_confirmation(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _project_with_sources(client)
        sources_page = client.get(f"/projects/{project_id}/sources")
        upload = client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(sources_page.text)},
            files={"source_file": ("note.txt", b"a" * 400, "text/plain")},
            follow_redirects=True,
        )
        source_id = upload.text.split('data-source-id="')[1].split('"')[0]

        confirm_page = client.get(f"/projects/{project_id}/sources/{source_id}/delete")
        unconfirmed = client.post(
            f"/projects/{project_id}/sources/{source_id}/delete",
            data={"csrf_token": _csrf(sources_page.text)},
        )
        still_there = client.get(f"/projects/{project_id}/sources")
        confirmed = client.post(
            f"/projects/{project_id}/sources/{source_id}/delete",
            data={"csrf_token": _csrf(sources_page.text), "confirm": source_id},
            follow_redirects=False,
        )
        after = client.get(f"/projects/{project_id}/sources")

    assert confirm_page.status_code == 200
    assert "از بین می‌رود" in confirm_page.text
    assert "باقی می‌ماند" in confirm_page.text
    assert 400 <= unconfirmed.status_code < 500
    assert source_id in still_there.text
    assert confirmed.status_code == 303
    assert source_id not in after.text


def test_running_pages_poll_a_fragment_instead_of_reloading(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _project_with_sources(client)
        processing = client.get(f"/projects/{project_id}/processing")
        fragment = client.get(f"/projects/{project_id}/processing/live")

    assert processing.status_code == 200
    assert fragment.status_code == 200
    assert 'id="processing-live"' in processing.text
    assert 'data-live-region' in processing.text
    # The live region owns the poll; nothing on the page reloads the whole document.
    for template_path in (TEMPLATES_ROOT / "projects").glob("*.html"):
        assert "data-auto-refresh" not in template_path.read_text(encoding="utf-8")
    assert "location.reload" not in (STATIC_ROOT / "app.js").read_text(encoding="utf-8")


def test_disabled_confirmation_states_the_reason(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _project_with_sources(client)
        page = client.get(f"/projects/{project_id}/sources").text

    assert 'disabled aria-describedby="corpus-confirm-hint"' in page
    assert 'id="corpus-confirm-hint"' in page


def test_default_theme_mode_preferences_and_overview_route(tmp_path: Path) -> None:
    app = create_app(
        _settings(tmp_path),
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    with TestClient(app) as client:
        login = client.get("/login")
        assert login.status_code == 200
        assert 'data-theme="cobalt"' in login.text
        assert 'data-mode="simple"' in login.text

        _login(client)
        projects = client.get("/projects")
        assert 'data-theme-value="cobalt"' in projects.text
        assert 'data-theme-value="wood"' in projects.text
        assert 'data-theme-value="olive"' in projects.text
        assert 'data-theme-value="slate"' in projects.text

        preference = client.post(
            "/ui/preferences",
            data={
                "csrf_token": _csrf(projects.text),
                "theme": "wood",
                "mode": "operator",
            },
        )
        assert preference.status_code == 204

        projects = client.get("/projects")
        assert 'data-theme="wood"' in projects.text
        assert 'data-mode="operator"' in projects.text

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
        project_id = created.headers["location"].split("/")[2]
        overview = client.get(f"/projects/{project_id}")

    assert overview.status_code == 200
    assert "خانهٔ گفتار" in overview.text
    assert "اخلاق کانت" in overview.text
    assert f'/projects/{project_id}/brief' in overview.text


def test_invalid_preferences_keep_safe_defaults(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        projects = client.get("/projects")
        response = client.post(
            "/ui/preferences",
            data={
                "csrf_token": _csrf(projects.text),
                "theme": "mixed-palette",
                "mode": "expert-plus",
            },
        )
        projects = client.get("/projects")

    assert response.status_code == 204
    assert 'data-theme="cobalt"' in projects.text
    assert 'data-mode="simple"' in projects.text


def _new_project(client: TestClient, *, mode: str = "explanatory") -> str:
    new_page = client.get("/projects/new")
    created = client.post(
        "/projects",
        data={
            "csrf_token": _csrf(new_page.text),
            "topic": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
            "audience": "دانشجوی علوم انسانی",
            "prior_knowledge": "introductory",
            "duration": "20",
            "mode": mode,
        },
        follow_redirects=False,
    )
    return created.headers["location"].split("/")[2]


def test_brief_form_edits_the_speech_mode(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _new_project(client)
        brief_page = client.get(f"/projects/{project_id}/brief")
        client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
                "mode": "critical",
                "action": "save",
            },
        )
        reloaded = client.get(f"/projects/{project_id}/brief").text

    assert 'value="critical" checked' in reloaded
    assert 'value="explanatory" checked' not in reloaded


def test_brief_form_keeps_the_stored_mode_when_none_is_submitted(tmp_path: Path) -> None:
    """An omitted radio must not silently reset a mode the user chose at creation."""

    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _new_project(client, mode="debate")
        brief_page = client.get(f"/projects/{project_id}/brief")
        client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
                "action": "save",
            },
        )
        reloaded = client.get(f"/projects/{project_id}/brief").text

    assert 'value="debate" checked' in reloaded


def test_brief_form_rejects_an_unknown_mode(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        project_id = _new_project(client)
        brief_page = client.get(f"/projects/{project_id}/brief")
        response = client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "چرا مفهوم دولت نزد ابن‌خلدون هنوز مهم است؟",
                "mode": "polemical",
                "action": "save",
            },
        )

    assert response.status_code == 422
    assert "رویکرد گفتار معتبر نیست." in response.text
