from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} matches, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new))


def sub_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    changed, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:120]!r}")
    write(path, changed)


# ---------------------------------------------------------------------------
# Central redaction and pure-ledger boundary.
# ---------------------------------------------------------------------------
OBS = "src/thesisound/observability.py"
replace_once(
    OBS,
    "_GEMINI_KEY_PATTERN = re.compile(r\"AIza[0-9A-Za-z_-]{20,}\")",
    """SENSITIVE_ATTRIBUTES = {\"query\", \"text\", \"excerpt\", \"filename\", \"topic\", \"phone\", \"prompt\"}\n\n_GEMINI_KEY_PATTERN = re.compile(r\"AIza[0-9A-Za-z_-]{20,}\")""",
)

sub_once(
    OBS,
    r"def redact_value\(value: Any\) -> Any:\n.*?\n\n\ndef _jsonable",
    '''def _sensitive_text(value: Any) -> str:\n    if isinstance(value, str):\n        return value\n    return json.dumps(\n        _jsonable(value),\n        ensure_ascii=False,\n        sort_keys=True,\n        separators=(\",\", \":\"),\n        default=str,\n    )\n\n\ndef _hashed_sensitive_value(value: Any) -> dict[str, Any]:\n    text = _sensitive_text(value)\n    return {\n        \"sha256\": hashlib.sha256(text.encode(\"utf-8\")).hexdigest(),\n        \"length\": len(text),\n    }\n\n\ndef _filename_identity(value: Any, container: Mapping[str, Any]) -> dict[str, Any]:\n    filename = str(value)\n    identity: dict[str, Any] = {\n        \"filename_sha256\": hashlib.sha256(filename.encode(\"utf-8\")).hexdigest()[:16],\n        \"extension\": Path(filename).suffix.lower(),\n    }\n    for key in (\"size_bytes\", \"file_size_bytes\", \"byte_count\"):\n        size = container.get(key)\n        if isinstance(size, int | float) and size >= 0:\n            identity[\"size_bytes\"] = int(size)\n            break\n    return identity\n\n\ndef redact_value(value: Any, *, store_payloads: bool = False) -> Any:\n    \"\"\"Apply the single observability privacy policy recursively.\n\n    Credential/identity carriers are always redacted. User-content attributes\n    are deterministic hash+length unless the one existing payload-storage\n    switch is enabled. Filenames are always represented by a deterministic\n    short hash plus extension (and file size when the caller supplied it), so\n    plaintext filenames remain confined to the project manifest.\n    \"\"\"\n\n    if isinstance(value, dict):\n        redacted: dict[str, Any] = {}\n        for raw_key, item in value.items():\n            key = str(raw_key)\n            normalized = key.casefold().replace(\"-\", \"_\")\n            if is_sensitive_key(key):\n                redacted[key] = \"[REDACTED]\"\n            elif normalized == \"filename\":\n                redacted[key] = _filename_identity(item, value)\n            elif normalized in SENSITIVE_ATTRIBUTES and not store_payloads:\n                redacted[key] = _hashed_sensitive_value(item)\n            else:\n                redacted[key] = redact_value(item, store_payloads=store_payloads)\n        return redacted\n    if isinstance(value, list):\n        return [redact_value(item, store_payloads=store_payloads) for item in value]\n    if isinstance(value, tuple):\n        return [redact_value(item, store_payloads=store_payloads) for item in value]\n    if isinstance(value, str):\n        return redact_text(value)\n    return value\n\n\ndef redact_exception_message(value: str | None) -> str | None:\n    if value is None:\n        return None\n    return redact_text(str(value))[:1_000]\n\n\ndef _jsonable''',
)

replace_once(
    OBS,
    "                    _json(spec.metadata),",
    "                    _json(redact_value(spec.metadata, store_payloads=self.store_payloads)),",
)
replace_once(
    OBS,
    '                    _truncate(_optional_text(event.get("error_message"))),',
    '                    redact_exception_message(_optional_text(event.get("error_message"))),',
)
replace_all(
    OBS,
    "            error_message=_truncate(str(error) or type(error).__name__),",
    "            error_message=redact_exception_message(str(error) or type(error).__name__),",
    expected=2,
)
replace_once(
    OBS,
    "                    _truncate(error_message),",
    "                    redact_exception_message(error_message),",
)
replace_all(
    OBS,
    "_json(redact_value(record.attributes))",
    "_json(redact_value(record.attributes, store_payloads=self.store_payloads))",
    expected=3,
)
replace_once(
    OBS,
    "                    _truncate(record.error_message),",
    "                    redact_exception_message(record.error_message),",
)
replace_once(
    OBS,
    "        serialized = _json(redact_value(_jsonable(payload))) + \"\\n\"",
    "        serialized = _json(\n            redact_value(_jsonable(payload), store_payloads=self.store_payloads)\n        ) + \"\\n\"",
)
replace_once(OBS, "        error_message=row[20],", "        error_message=redact_exception_message(row[20]),")
replace_once(OBS, "        error_message=row[16],", "        error_message=redact_exception_message(row[16]),")
# The span row has another error_message at index 16; replace the remaining occurrence.
replace_once(OBS, "        error_message=row[16],", "        error_message=redact_exception_message(row[16]),")
replace_once(OBS, "        error_message=row[17],", "        error_message=redact_exception_message(row[17]),")

sub_once(
    OBS,
    r"\n    def stage_summary\(.*?\n    def list_events\(",
    "\n    def list_events(",
)
sub_once(
    OBS,
    r"\n    def project_summary\(.*?\n    def read_artifact\(",
    "\n    def read_artifact(",
)

ROLLUP = '''from __future__ import annotations\n\nimport sqlite3\nfrom contextlib import closing\nfrom uuid import UUID\n\nfrom thesisound.observability import (\n    CacheHitRateSummary,\n    CostBreakdownRow,\n    ObservabilityLedger,\n    ProjectUsageSummary,\n    StageSummary,\n)\n\n\nclass ObservabilityRollup:\n    \"\"\"Read-only derived metrics over the observability ledger.\n\n    The ledger remains a persistence boundary. Aggregation SQL lives here so\n    CLI and web reporting share definitions without turning the store itself\n    into an analytics service.\n    \"\"\"\n\n    def __init__(self, ledger: ObservabilityLedger) -> None:\n        self.database_path = ledger.database_path\n\n    def project_summary(self, project_id: UUID) -> ProjectUsageSummary:\n        with closing(self._connect()) as connection:\n            row = connection.execute(\n                \"\"\"\n                SELECT COUNT(*),\n                       COUNT(*) FILTER (WHERE status = 'succeeded'),\n                       COUNT(*) FILTER (WHERE status = 'failed'),\n                       COUNT(*) FILTER (WHERE status = 'rejected'),\n                       COALESCE(SUM(provider_attempt_count), 0),\n                       COALESCE(SUM(input_tokens), 0),\n                       COALESCE(SUM(output_tokens), 0),\n                       COALESCE(SUM(thinking_tokens), 0),\n                       COALESCE(SUM(cached_tokens), 0),\n                       COALESCE(SUM(total_tokens), 0),\n                       COALESCE(SUM(latency_ms), 0),\n                       COALESCE(SUM(cost_micros), 0),\n                       COUNT(*) FILTER (\n                           WHERE status = 'succeeded' AND cost_micros IS NULL\n                       )\n                FROM model_calls\n                WHERE project_id = ?\n                \"\"\",\n                (str(project_id),),\n            ).fetchone()\n        values = row or (0,) * 13\n        return ProjectUsageSummary(\n            project_id=project_id,\n            call_count=int(values[0] or 0),\n            succeeded_count=int(values[1] or 0),\n            failed_count=int(values[2] or 0),\n            rejected_count=int(values[3] or 0),\n            provider_attempt_count=int(values[4] or 0),\n            input_tokens=int(values[5] or 0),\n            output_tokens=int(values[6] or 0),\n            thinking_tokens=int(values[7] or 0),\n            cached_tokens=int(values[8] or 0),\n            total_tokens=int(values[9] or 0),\n            total_latency_ms=int(values[10] or 0),\n            total_cost_micros=int(values[11] or 0),\n            unpriced_succeeded_count=int(values[12] or 0),\n        )\n\n    def stage_summary(self, project_id: UUID) -> list[StageSummary]:\n        with closing(self._connect()) as connection:\n            rows = connection.execute(\n                \"\"\"\n                WITH child_time AS (\n                    SELECT parent_span_id AS parent, SUM(duration_ms) AS ms\n                      FROM pipeline_spans\n                     WHERE project_id = ? AND parent_span_id IS NOT NULL\n                     GROUP BY parent_span_id\n                )\n                SELECT s.name, s.component,\n                       COUNT(*),\n                       COALESCE(SUM(s.duration_ms), 0),\n                       MAX(0, COALESCE(SUM(s.duration_ms - COALESCE(c.ms, 0)), 0)),\n                       COUNT(*) FILTER (WHERE s.status = 'error')\n                  FROM pipeline_spans s\n                  LEFT JOIN child_time c ON c.parent = s.span_id\n                 WHERE s.project_id = ?\n                 GROUP BY s.name, s.component\n                 ORDER BY 5 DESC\n                \"\"\",\n                (str(project_id), str(project_id)),\n            ).fetchall()\n        return [\n            StageSummary(\n                name=row[0],\n                component=row[1],\n                call_count=row[2],\n                total_ms=row[3],\n                avg_ms=round(row[3] / row[2]) if row[2] else 0,\n                self_total_ms=row[4],\n                self_avg_ms=round(row[4] / row[2]) if row[2] else 0,\n                error_count=row[5],\n            )\n            for row in rows\n        ]\n\n    def cost_breakdown(self, project_id: UUID) -> list[CostBreakdownRow]:\n        with closing(self._connect()) as connection:\n            rows = connection.execute(\n                \"\"\"\n                SELECT stage, provider, COALESCE(resolved_model, requested_model),\n                       COUNT(*),\n                       COUNT(*) FILTER (\n                           WHERE status = 'succeeded' AND cost_micros IS NULL\n                       ),\n                       COALESCE(SUM(cost_micros), 0),\n                       COALESCE(SUM(total_tokens), 0)\n                FROM model_calls\n                WHERE project_id = ? AND status = 'succeeded'\n                GROUP BY stage, provider, COALESCE(resolved_model, requested_model)\n                ORDER BY SUM(cost_micros) DESC\n                \"\"\",\n                (str(project_id),),\n            ).fetchall()\n        return [\n            CostBreakdownRow(\n                stage=row[0],\n                provider=row[1],\n                model=row[2],\n                call_count=row[3],\n                unpriced_count=row[4],\n                total_cost_micros=row[5],\n                total_tokens=row[6],\n            )\n            for row in rows\n        ]\n\n    def cache_hit_rates(self, project_id: UUID) -> list[CacheHitRateSummary]:\n        with closing(self._connect()) as connection:\n            rows = connection.execute(\n                \"\"\"\n                SELECT json_extract(attributes_json, '$.cache') AS cache,\n                       COUNT(*) FILTER (\n                           WHERE json_extract(attributes_json, '$.result') = 'hit'\n                       ),\n                       COUNT(*) FILTER (\n                           WHERE json_extract(attributes_json, '$.result') = 'miss'\n                       )\n                FROM pipeline_events\n                WHERE project_id = ? AND name = 'cache.lookup'\n                GROUP BY cache\n                ORDER BY cache\n                \"\"\",\n                (str(project_id),),\n            ).fetchall()\n        return [\n            CacheHitRateSummary(cache=row[0], hits=row[1], misses=row[2])\n            for row in rows\n            if row[0] is not None\n        ]\n\n    def _connect(self) -> sqlite3.Connection:\n        connection = sqlite3.connect(self.database_path, timeout=30)\n        connection.execute(\"PRAGMA busy_timeout=30000\")\n        connection.execute(\"PRAGMA query_only=ON\")\n        return connection\n'''
write("src/thesisound/services/observability_rollup.py", ROLLUP)

# ---------------------------------------------------------------------------
# Logging uses the same redactor and scrubs exception text too.
# ---------------------------------------------------------------------------
LOGGING = "src/thesisound/logging_setup.py"
replace_once(
    LOGGING,
    "class RedactingFilter(logging.Filter):\n",
    "class RedactingFilter(logging.Filter):\n",
)
replace_once(
    LOGGING,
    """    def filter(self, record: logging.LogRecord) -> bool:\n        record.msg = redact_text(record.getMessage())\n""",
    """    def __init__(self, *, store_payloads: bool = False) -> None:\n        super().__init__()\n        self.store_payloads = store_payloads\n\n    def filter(self, record: logging.LogRecord) -> bool:\n        record.msg = redact_text(record.getMessage())\n""",
)
replace_once(
    LOGGING,
    '            record.__dict__[key] = "[REDACTED]" if is_sensitive_key(key) else redact_value(value)',
    '            record.__dict__[key] = (\n                "[REDACTED]"\n                if is_sensitive_key(key)\n                else redact_value(value, store_payloads=self.store_payloads)\n            )',
)
replace_all(
    LOGGING,
    '            payload["exception"] = self.formatException(record.exc_info)',
    '            payload["exception"] = redact_text(self.formatException(record.exc_info))',
    expected=1,
)
replace_once(
    LOGGING,
    '            line = f"{line}\\n{self.formatException(record.exc_info)}"',
    '            line = f"{line}\\n{redact_text(self.formatException(record.exc_info))}"',
)
replace_once(
    LOGGING,
    '            "redact": {"()": RedactingFilter},',
    '            "redact": {\n                "()": RedactingFilter,\n                "store_payloads": settings.observability_store_payloads,\n            },',
)

# ---------------------------------------------------------------------------
# Reporter/export: remove the second redactor; consume the central policy and
# the rollup service.
# ---------------------------------------------------------------------------
REPORT = "src/thesisound/services/observability_reporting.py"
replace_once(REPORT, "import hmac\n", "")
replace_once(REPORT, "import secrets\n", "")
replace_once(
    REPORT,
    "from thesisound.observability import ObservabilityLedger, redact_value\n",
    "from thesisound.observability import SENSITIVE_ATTRIBUTES, ObservabilityLedger, redact_value\nfrom thesisound.services.observability_rollup import ObservabilityRollup\n",
)
sub_once(
    REPORT,
    r"\n# Export only code-controlled operational attributes\..*?\n\n@dataclass",
    "\n\n@dataclass",
)
replace_once(
    REPORT,
    "    def __init__(self, ledger: ObservabilityLedger) -> None:\n        self.ledger = ledger\n",
    "    def __init__(self, ledger: ObservabilityLedger) -> None:\n        self.ledger = ledger\n        self.rollup = ObservabilityRollup(ledger)\n",
)
replace_once(REPORT, "        fingerprint_key = secrets.token_bytes(32)\n", "")
replace_all(REPORT, "self._export_span_row(row, fingerprint_key)", "self._export_span_row(row)", expected=1)
replace_all(REPORT, "self._export_event_row(row, fingerprint_key)", "self._export_event_row(row)", expected=1)
replace_all(REPORT, "self._export_model_call_row(row, fingerprint_key)", "self._export_model_call_row(row)", expected=1)
replace_once(REPORT, '                "format_version": 2,', '                "format_version": 3,')
replace_once(
    REPORT,
    '''                "redaction": {\n                    "policy": "allowlisted operational fields; arbitrary free text omitted",\n                    "opaque_fields": "HMAC-SHA256 keyed per export; key is not persisted",\n                },''',
    '''                "redaction": {\n                    "policy": "thesisound.observability.redact_value; payload storage forced off",\n                    "sensitive_attributes": sorted(SENSITIVE_ATTRIBUTES),\n                    "fingerprints": "deterministic SHA-256; filenames use a 16-hex SHA prefix",\n                },''',
)
replace_once(REPORT, "        summary = self.ledger.project_summary(project_id)", "        summary = self.rollup.project_summary(project_id)")
replace_once(REPORT, '            "cost_breakdown": self.ledger.cost_breakdown(project_id),', '            "cost_breakdown": self.rollup.cost_breakdown(project_id),')
replace_once(REPORT, '            "stage_summary": self.ledger.stage_summary(project_id)[:20],', '            "stage_summary": self.rollup.stage_summary(project_id)[:20],')
replace_once(REPORT, '            "cache_rates": self.ledger.cache_hit_rates(project_id),', '            "cache_rates": self.rollup.cache_hit_rates(project_id),')

sub_once(
    REPORT,
    r"    @staticmethod\n    def _export_span_row\(.*?\n    @staticmethod\n    def _safe_dict",
    '''    @staticmethod\n    def _export_span_row(row: sqlite3.Row) -> dict[str, Any]:\n        item = dict(row)\n        item[\"attributes\"] = ObservabilityReporter._load_json(\n            item.pop(\"attributes_json\", \"{}\")\n        )\n        item[\"metrics\"] = ObservabilityReporter._load_json(\n            item.pop(\"metrics_json\", \"{}\")\n        )\n        return redact_value(item, store_payloads=False)\n\n    @staticmethod\n    def _export_event_row(row: sqlite3.Row) -> dict[str, Any]:\n        item = dict(row)\n        item[\"attributes\"] = ObservabilityReporter._load_json(\n            item.pop(\"attributes_json\", \"{}\")\n        )\n        return redact_value(item, store_payloads=False)\n\n    @staticmethod\n    def _export_model_call_row(row: sqlite3.Row) -> dict[str, Any]:\n        item = dict(row)\n        item[\"metadata\"] = ObservabilityReporter._load_json(\n            item.pop(\"metadata_json\", \"{}\")\n        )\n        return redact_value(item, store_payloads=False)\n\n    @staticmethod\n    def _safe_dict''',
)
replace_once(
    REPORT,
    "        return redact_value(loaded) if isinstance(loaded, dict) else {}",
    "        return redact_value(loaded, store_payloads=True) if isinstance(loaded, dict) else {}",
)
replace_once(REPORT, '        connection.execute("PRAGMA journal_mode=WAL")\n', "")

# ---------------------------------------------------------------------------
# CLI consumes rollups rather than derived-query methods on the ledger.
# ---------------------------------------------------------------------------
CLI = "src/thesisound/observability_cli.py"
replace_once(
    CLI,
    "from thesisound.services.observability_reporting import ObservabilityReporter\n",
    "from thesisound.services.observability_reporting import ObservabilityReporter\nfrom thesisound.services.observability_rollup import ObservabilityRollup\n",
)
replace_once(
    CLI,
    "        ledger = ledger_from_settings(settings)\n        summary = ledger.project_summary(project_id)\n",
    "        ledger = ledger_from_settings(settings)\n        rollup = ObservabilityRollup(ledger)\n        summary = rollup.project_summary(project_id)\n",
)
replace_once(
    CLI,
    "        ledger = ledger_from_settings(settings)\n        console = Console()\n        rows = ledger.stage_summary(project_id)\n",
    "        ledger = ledger_from_settings(settings)\n        rollup = ObservabilityRollup(ledger)\n        console = Console()\n        rows = rollup.stage_summary(project_id)\n",
)
replace_once(CLI, "        cache_rows = ledger.cache_hit_rates(project_id)", "        cache_rows = rollup.cache_hit_rates(project_id)")
replace_once(
    CLI,
    "        ledger = ledger_from_settings(settings)\n        console = Console()\n        summary = ledger.project_summary(project_id)\n",
    "        ledger = ledger_from_settings(settings)\n        rollup = ObservabilityRollup(ledger)\n        console = Console()\n        summary = rollup.project_summary(project_id)\n",
)
replace_once(CLI, "        rows = ledger.cost_breakdown(project_id)", "        rows = rollup.cost_breakdown(project_id)")

# ---------------------------------------------------------------------------
# Operator means authorization AND the existing operator presentation mode.
# ---------------------------------------------------------------------------
APP = "src/thesisound/web/app.py"
replace_once(
    APP,
    '''        payload: dict[str, object] = {\n            "request": request,\n            "csrf_token": _ensure_csrf(request),\n            "current_user": (account.label if (account := _current_account(request)) else None),''',
    '''        account = _current_account(request)\n        payload: dict[str, object] = {\n            "request": request,\n            "csrf_token": _ensure_csrf(request),\n            "current_user": account.label if account else None,\n            "is_operator": account is not None and account.role == "operator",''',
)

ROUTES = "src/thesisound/web/observability_routes.py"
replace_once(
    ROUTES,
    '''    def require_operator(request: Request, project_id: UUID) -> Response | None:\n        if redirect := login_redirect(request):\n            return redirect\n        if not authenticated_operator(request):\n            return RedirectResponse(f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)\n        return None\n''',
    '''    def operator_mode(request: Request) -> bool:\n        return request.session.get("ui_mode", "simple") == "operator"\n\n    def require_operator(request: Request, project_id: UUID) -> Response | None:\n        if redirect := login_redirect(request):\n            return redirect\n        if not authenticated_operator(request) or not operator_mode(request):\n            return RedirectResponse(f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)\n        return None\n''',
)
replace_once(
    ROUTES,
    '''        if not authenticated_operator(request):\n            return HTMLResponse("", status_code=403)''',
    '''        if not authenticated_operator(request) or not operator_mode(request):\n            return HTMLResponse("", status_code=403)''',
)

for template in (
    "src/thesisound/web/templates/projects/_processing_live.html",
    "src/thesisound/web/templates/projects/_episode_live.html",
    "src/thesisound/web/templates/projects/_script_live.html",
    "src/thesisound/web/templates/projects/_audio_live.html",
):
    replace_once(
        template,
        "{% set current_span = observability_current_span(project.project_id) if ui_mode == 'operator' else none %}",
        "{% set current_span = observability_current_span(project.project_id) if is_operator and ui_mode == 'operator' else none %}",
    )

NAV = "src/thesisound/web/templates/projects/_workflow_navigation.html"
replace_once(
    NAV,
    '''  <div class="workflow-rail__rewind operator-only">\n    <span>عملیات:</span>\n    <a href="/projects/{{ project.project_id }}/observability">ردیابی، هزینه و خطاها</a>\n  </div>''',
    '''  {% if is_operator and ui_mode == 'operator' %}\n  <div class="workflow-rail__rewind operator-only">\n    <span>عملیات:</span>\n    <a href="/projects/{{ project.project_id }}/observability">ردیابی، هزینه و خطاها</a>\n  </div>\n  {% endif %}''',
)

# ---------------------------------------------------------------------------
# Tests: use the rollup service, assert the exact central privacy contract,
# and require both role and UI mode for the operator surface.
# ---------------------------------------------------------------------------
TEST_OBS = "tests/test_observability.py"
text = read(TEST_OBS)
text = text.replace(
    "from thesisound.observability import (\n",
    "from thesisound.observability import (\n    SENSITIVE_ATTRIBUTES,\n",
    1,
)
text = text.replace(
    ")\n\n\nclass FakePool:",
    ")\nfrom thesisound.services.observability_rollup import ObservabilityRollup\n\n\nclass FakePool:",
    1,
)
for method in ("project_summary", "stage_summary", "cost_breakdown", "cache_hit_rates"):
    text = text.replace(f"ledger.{method}(", f"ObservabilityRollup(ledger).{method}(")
text += '''\n\ndef test_sensitive_attribute_policy_uses_one_payload_switch(tmp_path: Path) -> None:\n    project_id = uuid4()\n    metadata = {\n        "query": "پرسش خصوصی",\n        "topic": "موضوع خصوصی",\n        "filename": "نام شخصی.pdf",\n        "size_bytes": 1234,\n        "phone": "09121234567",\n    }\n\n    private = ObservabilityLedger(\n        tmp_path / "private.sqlite3",\n        tmp_path / "private-artifacts",\n        store_payloads=False,\n    )\n    spec = ModelCallSpec(\n        project_id=project_id,\n        stage="source_discovery",\n        operation="google_search",\n        provider="gemini",\n        requested_model="gemini-test",\n        metadata=metadata,\n    )\n    private.begin_call(spec, {"prompt": "متن خصوصی"})\n    stored = private.get_call(spec.call_id).metadata\n    assert stored["query"]["sha256"]\n    assert stored["query"]["length"] == len("پرسش خصوصی")\n    assert stored["topic"]["sha256"]\n    assert stored["filename"] == {\n        "filename_sha256": stored["filename"]["filename_sha256"],\n        "extension": ".pdf",\n        "size_bytes": 1234,\n    }\n    assert len(stored["filename"]["filename_sha256"]) == 16\n    assert stored["phone"] == "[REDACTED]"\n    assert set(SENSITIVE_ATTRIBUTES) == {\n        "query", "text", "excerpt", "filename", "topic", "phone", "prompt"\n    }\n\n    private_second = ObservabilityLedger(\n        tmp_path / "private-second.sqlite3",\n        tmp_path / "private-second-artifacts",\n        store_payloads=False,\n    )\n    second_spec = spec.model_copy(update={"call_id": uuid4()})\n    private_second.begin_call(second_spec, {"prompt": "متن خصوصی"})\n    second = private_second.get_call(second_spec.call_id).metadata\n    assert second["query"]["sha256"] == stored["query"]["sha256"]\n    assert second["filename"]["filename_sha256"] == stored["filename"]["filename_sha256"]\n\n    payloads = ObservabilityLedger(\n        tmp_path / "payloads.sqlite3",\n        tmp_path / "payload-artifacts",\n        store_payloads=True,\n    )\n    payload_spec = spec.model_copy(update={"call_id": uuid4()})\n    payloads.begin_call(payload_spec, {"prompt": "متن خصوصی"})\n    visible = payloads.get_call(payload_spec.call_id).metadata\n    assert visible["query"] == "پرسش خصوصی"\n    assert visible["topic"] == "موضوع خصوصی"\n    assert "نام شخصی.pdf" not in str(visible["filename"])\n    assert visible["phone"] == "[REDACTED]"\n\n\ndef test_exception_messages_are_redacted_before_model_persistence(tmp_path: Path) -> None:\n    ledger = _ledger(tmp_path)\n    spec = ModelCallSpec(\n        stage="document_map",\n        operation="structured_text",\n        provider="gemini",\n        requested_model="gemini-test",\n    )\n    ledger.begin_call(spec, {"prompt": "x"})\n    ledger.record_attempt(\n        spec.call_id,\n        logical_attempt=1,\n        provider_attempt=1,\n        event={\n            "status": "failed",\n            "error_message": "phone 09121234567 key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ /home/alice/file",\n        },\n    )\n    ledger.fail(\n        spec.call_id,\n        RuntimeError("phone 09121234567 key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ /home/alice/file"),\n    )\n\n    detail = ledger.get_call(spec.call_id)\n    rendered = f"{detail.call.error_message} {detail.attempts[0].error_message}"\n    assert "09121234567" not in rendered\n    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in rendered\n    assert "/home/alice" not in rendered\n    assert "[REDACTED_PHONE]" in rendered\n    assert "[REDACTED_SECRET]" in rendered\n    assert "[HOME]" in rendered\n'''
write(TEST_OBS, text)

TEST_LOG = "tests/test_logging_setup.py"
text = read(TEST_LOG)
text += '''\n\ndef test_redacting_filter_applies_sensitive_attribute_payload_switch() -> None:\n    private = _record(\n        "search",\n        extra={"query": "پرسش خصوصی", "filename": "نام شخصی.pdf", "size_bytes": 99},\n    )\n    RedactingFilter(store_payloads=False).filter(private)\n    assert private.query["sha256"]  # type: ignore[attr-defined]\n    assert private.query["length"] == len("پرسش خصوصی")  # type: ignore[attr-defined]\n    assert private.filename["extension"] == ".pdf"  # type: ignore[attr-defined]\n    assert private.filename["size_bytes"] == 99  # type: ignore[attr-defined]\n\n    enabled = _record("search", extra={"query": "پرسش خصوصی"})\n    RedactingFilter(store_payloads=True).filter(enabled)\n    assert enabled.query == "پرسش خصوصی"  # type: ignore[attr-defined]\n\n\ndef test_formatters_redact_exception_messages() -> None:\n    try:\n        raise ValueError("phone 09121234567 key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ /home/alice/file")\n    except ValueError:\n        import sys\n\n        record = _record("failed", level=logging.ERROR, exc_info=sys.exc_info())\n\n    json_line = JsonFormatter().format(record)\n    console_line = ConsoleFormatter().format(record)\n    for rendered in (json_line, console_line):\n        assert "09121234567" not in rendered\n        assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in rendered\n        assert "/home/alice" not in rendered\n'''
write(TEST_LOG, text)

ROLLUP_TEST = '''from __future__ import annotations\n\nfrom datetime import UTC, datetime, timedelta\nfrom uuid import uuid4\n\nfrom thesisound.observability import ModelCallSpec, ProviderMetadata\nfrom thesisound.modeling import ModelUsage\nfrom thesisound.services.observability_rollup import ObservabilityRollup\nfrom thesisound.tracing import EventRecord, SpanContext, SpanRecord\n\n\ndef _span(ledger, *, trace_id, project_id, span_id, name, duration_ms, parent=None):\n    started = datetime(2026, 1, 1, tzinfo=UTC)\n    record = SpanRecord(\n        context=SpanContext(trace_id=trace_id, span_id=span_id, project_id=project_id),\n        parent_span_id=parent,\n        name=name,\n        component="test",\n        kind="stage",\n        started_at=started,\n        process="test",\n        pid=1,\n    )\n    ledger.start_span(record)\n    record.status = "ok"\n    record.ended_at = started + timedelta(milliseconds=duration_ms)\n    record.duration_ms = duration_ms\n    ledger.end_span(record)\n\n\ndef test_rollup_owns_self_time_cache_usage_and_cost_views(ledger) -> None:\n    project_id = uuid4()\n    trace_id = uuid4()\n    root = uuid4()\n    child = uuid4()\n    _span(ledger, trace_id=trace_id, project_id=project_id, span_id=root, name="run", duration_ms=1000)\n    _span(\n        ledger,\n        trace_id=trace_id,\n        project_id=project_id,\n        span_id=child,\n        name="child",\n        duration_ms=400,\n        parent=root,\n    )\n    for result in ("hit", "miss"):\n        ledger.record_event(\n            EventRecord(\n                event_id=uuid4(),\n                trace_id=trace_id,\n                span_id=root,\n                project_id=project_id,\n                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),\n                name="cache.lookup",\n                component="cache",\n                attributes={"cache": "document_map", "result": result},\n            )\n        )\n\n    spec = ModelCallSpec(\n        project_id=project_id,\n        stage="document_map",\n        operation="structured_text",\n        provider="test",\n        requested_model="unpriced-model",\n    )\n    ledger.begin_call(spec, {"prompt": "x"})\n    ledger.provider_succeeded(\n        spec.call_id,\n        response_payload={"text": "ok"},\n        usage=ModelUsage(input_tokens=2, output_tokens=1, total_tokens=3),\n        provider_metadata=ProviderMetadata(resolved_model="unpriced-model"),\n    )\n    ledger.succeed(spec.call_id, {"ok": True})\n\n    rollup = ObservabilityRollup(ledger)\n    stages = {row.name: row for row in rollup.stage_summary(project_id)}\n    assert stages["run"].total_ms == 1000\n    assert stages["run"].self_total_ms == 600\n    assert stages["child"].self_total_ms == 400\n    cache = rollup.cache_hit_rates(project_id)[0]\n    assert cache.cache == "document_map"\n    assert cache.hit_rate == 0.5\n    summary = rollup.project_summary(project_id)\n    assert summary.call_count == 1\n    assert summary.total_tokens == 3\n    assert summary.unpriced_succeeded_count == 1\n    cost = rollup.cost_breakdown(project_id)[0]\n    assert cost.unpriced_count == 1\n'''
write("tests/test_observability_rollups.py", ROLLUP_TEST)

PHASE = "tests/test_observability_phase56.py"
text = read(PHASE)
text = text.replace(
    '''            "filename": "نام شخصی.pdf",\n            "query": ["پرسش خصوصی کاربر"],\n            "path": "/home/alice/private/source.pdf",\n            "central_question": "این پرسش نباید صادر شود",\n            "nested": {"description": "این توضیح هم خصوصی است"},''',
    '''            "filename": "نام شخصی.pdf",\n            "size_bytes": 4321,\n            "query": ["پرسش خصوصی کاربر"],\n            "topic": "موضوع خصوصی",\n            "excerpt": "گزیده خصوصی",\n            "path": "/home/alice/private/source.pdf",''',
    1,
)
text = text.replace(
    '''        attributes={\n            "pipeline_code_version": code_version,\n            "private_title": "عنوان خصوصی که نباید صادر شود",\n        },''',
    '''        attributes={\n            "pipeline_code_version": code_version,\n            "topic": "عنوان خصوصی که نباید صادر شود",\n        },''',
    1,
)
text = text.replace(
    '''        attributes={\n            "cache": "document_map",\n            "result": cache_result,\n            "private_note": "یادداشت خصوصی",\n        },''',
    '''        attributes={\n            "cache": "document_map",\n            "result": cache_result,\n            "excerpt": "یادداشت خصوصی",\n        },''',
    1,
)
text = text.replace('    assert manifest["format_version"] == 2', '    assert manifest["format_version"] == 3', 1)
text = text.replace(
    '    assert "allowlisted operational fields" in manifest["redaction"]["policy"]',
    '    assert "thesisound.observability.redact_value" in manifest["redaction"]["policy"]',
    1,
)
text = text.replace(
    '''        "این پرسش نباید صادر شود",\n        "این توضیح هم خصوصی است",\n        "عنوان خصوصی که نباید صادر شود",\n        "یادداشت خصوصی",\n        "source-private-id",''',
    '''        "موضوع خصوصی",\n        "گزیده خصوصی",\n        "عنوان خصوصی که نباید صادر شود",\n        "یادداشت خصوصی",''',
    1,
)
text = text.replace(
    '''    call_row = json.loads((export_dir / "model_calls.jsonl").read_text().splitlines()[0])\n    assert call_row["metadata"] == {"provider": "test"}\n    assert call_row["subject_id"]["fingerprint"]\n    assert call_row["subject_id"]["length"] == len("source-private-id")\n    event_row = json.loads((export_dir / "events.jsonl").read_text().splitlines()[0])\n    assert event_row["attributes"] == {"cache": "document_map", "result": "hit"}\n''',
    '''    call_row = json.loads((export_dir / "model_calls.jsonl").read_text().splitlines()[0])\n    assert call_row["subject_id"] == "source-private-id"\n    assert call_row["metadata"]["provider"] == "test"\n    assert call_row["metadata"]["query"]["sha256"]\n    assert call_row["metadata"]["topic"]["sha256"]\n    assert call_row["metadata"]["excerpt"]["sha256"]\n    assert call_row["metadata"]["filename"]["extension"] == ".pdf"\n    assert call_row["metadata"]["filename"]["size_bytes"] == 4321\n    event_row = json.loads((export_dir / "events.jsonl").read_text().splitlines()[0])\n    assert event_row["attributes"]["cache"] == "document_map"\n    assert event_row["attributes"]["result"] == "hit"\n    assert event_row["attributes"]["excerpt"]["sha256"]\n\n    second_dir = tmp_path / "export-second"\n    reporter.export_project(project_id, second_dir)\n    second_call = json.loads((second_dir / "model_calls.jsonl").read_text().splitlines()[0])\n    assert (\n        second_call["metadata"]["query"]["sha256"]\n        == call_row["metadata"]["query"]["sha256"]\n    )\n    assert (\n        second_call["metadata"]["filename"]["filename_sha256"]\n        == call_row["metadata"]["filename"]["filename_sha256"]\n    )\n''',
    1,
)
text = text.replace(
    '''    # An actual operator is authorized regardless of the presentation mode.\n    with TestClient(app) as client:\n        _login_password(client, "operator-user", "operator-pass")\n        page = client.get(f"/projects/{project.project_id}/observability")\n        assert page.status_code == 200\n''',
    '''    # The real operator role authorizes the data, while the existing UI mode\n    # still gates whether the technical operator surface is presented.\n    with TestClient(app) as client:\n        _login_password(client, "operator-user", "operator-pass")\n        simple = client.get(\n            f"/projects/{project.project_id}/observability", follow_redirects=False\n        )\n        assert simple.status_code == 303\n        assert client.get(f"/projects/{project.project_id}/observability/live").status_code == 403\n\n        preferences = client.get("/projects")\n        changed = client.post(\n            "/ui/preferences",\n            data={"csrf_token": _csrf(preferences.text), "mode": "operator"},\n        )\n        assert changed.status_code == 204\n\n        page = client.get(f"/projects/{project.project_id}/observability")\n        assert page.status_code == 200\n''',
    1,
)
write(PHASE, text)

# Ensure the old rollup API is gone from the ledger and all source callers use
# the dedicated service.
obs_text = read(OBS)
for method in ("project_summary", "stage_summary", "cost_breakdown", "cache_hit_rates"):
    if f"    def {method}(" in obs_text:
        raise RuntimeError(f"ObservabilityLedger still owns derived method: {method}")

for path in Path("src").rglob("*.py"):
    if path.as_posix().endswith("services/observability_rollup.py"):
        continue
    source = path.read_text(encoding="utf-8")
    for needle in ("ledger.project_summary(", "ledger.stage_summary(", "ledger.cost_breakdown(", "ledger.cache_hit_rates("):
        if needle in source:
            raise RuntimeError(f"derived ledger call remains in {path}: {needle}")

print("Observability plan alignment patch applied.")
