from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Missing final conformance anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/thesisound/observability.py",
    '''            existing = connection.execute(\n                "SELECT started_at, finished_at FROM pipeline_runs "\n                "WHERE workflow_run_id = ?",\n                (str(workflow_run_id),),\n            ).fetchone()\n''',
    '''            existing = connection.execute(\n                "SELECT started_at FROM pipeline_runs WHERE workflow_run_id = ?",\n                (str(workflow_run_id),),\n            ).fetchone()\n''',
)
replace(
    "src/thesisound/observability.py",
    '''            finished_at = (\n                _from_db_timestamp(existing[1]) if existing[1] else _now()\n            )\n            started_at = _from_db_timestamp(existing[0])\n''',
    '''            # A workflow may have multiple root spans sharing this run id.\n            # Each terminal root refreshes the rollup so the final span contributes\n            # both its model calls and the actual run finish time.\n            finished_at = _now()\n            started_at = _from_db_timestamp(existing[0])\n''',
)
replace(
    "tests/test_pipeline_runs.py",
    '''    assert first == second\n    assert second.call_count == 0\n''',
    '''    assert second.finished_at is not None\n    assert first.finished_at is not None\n    assert second.finished_at >= first.finished_at\n    assert second.call_count == first.call_count == 0\n''',
)

replace(
    "src/thesisound/services/url_probe.py",
    "from typing import Literal\n",
    "from typing import Any, Literal\n",
)
replace(
    "src/thesisound/services/url_probe.py",
    "from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener\n",
    "from urllib.request import (\n"
    "    HTTPRedirectHandler,\n"
    "    OpenerDirector,\n"
    "    ProxyHandler,\n"
    "    Request,\n"
    "    build_opener,\n"
    ")\n",
)
replace(
    "src/thesisound/services/url_probe.py",
    "_DEAD_STATUSES = {404, 410, 451}\n\n\n@dataclass",
    '''_DEAD_STATUSES = {404, 410, 451}\n\n\nclass _NoRedirectHandler(HTTPRedirectHandler):\n    """Expose the original 3xx instead of following an unvalidated host."""\n\n    def redirect_request(\n        self,\n        req: Request,\n        fp: Any,\n        code: int,\n        msg: str,\n        headers: Any,\n        newurl: str,\n    ) -> None:\n        return None\n\n\n@dataclass''',
)
replace(
    "src/thesisound/services/url_probe.py",
    "    return build_opener(ProxyHandler(proxies))\n",
    "    return build_opener(ProxyHandler(proxies), _NoRedirectHandler())\n",
)
replace(
    "tests/test_url_probe.py",
    '''    def build(handler: ProxyHandler):\n        captured.append(handler)\n        return fake\n''',
    '''    def build(*handlers: object):\n        proxy_handler = next(\n            handler for handler in handlers if isinstance(handler, ProxyHandler)\n        )\n        captured.append(proxy_handler)\n        assert any(\n            isinstance(handler, url_probe._NoRedirectHandler)\n            for handler in handlers\n        )\n        return fake\n''',
)

replace(
    ".github/workflows/ci.yml",
    '''      - name: Set up Python\n        uses: actions/setup-python@v6\n        with:\n          python-version: "3.12"\n\n      - name: Set up uv\n''',
    '''      - name: Set up Python\n        uses: actions/setup-python@v6\n        with:\n          python-version: "3.12"\n\n      - name: Install system dependencies\n        run: sudo apt-get update && sudo apt-get install -y ffmpeg\n\n      - name: Set up uv\n''',
)
