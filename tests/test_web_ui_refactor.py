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
        test_otp_phone="0912000000",
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
            "phone": "0912000000",
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
        r'html\[data-theme="(?P<theme>cobalt|wood|olive)"\]'
        r'(?:,\s*:root)?\s*\{(?P<body>.*?)\n\}',
        re.DOTALL,
    )
    for match in pattern.finditer(css):
        blocks[match.group("theme")] = set(
            re.findall(r"--([a-z0-9-]+)\s*:", match.group("body"))
        )

    assert set(blocks) == {"cobalt", "wood", "olive"}
    assert blocks["cobalt"] == blocks["wood"] == blocks["olive"]
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
        assert 'data-theme-value="wood"' in login.text
        assert 'data-theme-value="olive"' in login.text

        _login(client)
        projects = client.get("/projects")
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
