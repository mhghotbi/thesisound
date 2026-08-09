from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Missing item 5 correction anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/thesisound/observability.py",
    "from contextlib import closing\n",
    "from contextlib import closing, suppress\n",
)
replace(
    "src/thesisound/observability.py",
    '''            try:\n                self.ledger.begin_run(\n                    PipelineRunSpec(\n                        workflow_run_id=record.context.workflow_run_id,\n                        project_id=record.context.project_id,\n                        trace_id=record.context.trace_id,\n                        kind=record.component,\n                        started_at=record.started_at,\n                    )\n                )\n            except Exception:\n                # Observability enrichment must never break the traced workflow.\n                pass\n''',
    '''            with suppress(Exception):\n                self.ledger.begin_run(\n                    PipelineRunSpec(\n                        workflow_run_id=record.context.workflow_run_id,\n                        project_id=record.context.project_id,\n                        trace_id=record.context.trace_id,\n                        kind=record.component,\n                        started_at=record.started_at,\n                    )\n                )\n''',
)
replace(
    "src/thesisound/observability.py",
    '''            try:\n                self.ledger.finish_run(\n                    record.context.workflow_run_id,\n                    status="failed" if record.status == "error" else "succeeded",\n                    error_message=record.error_message,\n                )\n            except Exception:\n                # A rollup write is secondary to the workflow and span record.\n                pass\n''',
    '''            with suppress(Exception):\n                self.ledger.finish_run(\n                    record.context.workflow_run_id,\n                    status="failed" if record.status == "error" else "succeeded",\n                    error_message=record.error_message,\n                )\n''',
)
replace(
    "tests/test_ledger_spans_and_events.py",
    '''    with ledger_tracer.span(\n        "script.run",\n        component="script",\n        kind="stage",\n        project_id=project_id,\n        workflow_run_id=run_id,\n    ):\n        with ledger_tracer.span(\n            "script.child",\n            component="script",\n            kind="stage",\n            workflow_run_id=run_id,\n        ):\n            pass\n''',
    '''    with (\n        ledger_tracer.span(\n            "script.run",\n            component="script",\n            kind="stage",\n            project_id=project_id,\n            workflow_run_id=run_id,\n        ),\n        ledger_tracer.span(\n            "script.child",\n            component="script",\n            kind="stage",\n            workflow_run_id=run_id,\n        ),\n    ):\n        pass\n''',
)
replace(
    "tests/test_pipeline_runs.py",
    '''    _record_call(\n        ledger, run_id=run_id, model="model-b", prompt_id="failed", prompt_version="1.0.0", status="failed"\n    )\n''',
    '''    _record_call(\n        ledger,\n        run_id=run_id,\n        model="model-b",\n        prompt_id="failed",\n        prompt_version="1.0.0",\n        status="failed",\n    )\n''',
)
replace(
    "tests/test_pipeline_runs.py",
    '''    _record_call(\n        ledger, run_id=run_id, model="model-b", prompt_id="rejected", prompt_version="1.0.0", status="rejected"\n    )\n''',
    '''    _record_call(\n        ledger,\n        run_id=run_id,\n        model="model-b",\n        prompt_id="rejected",\n        prompt_version="1.0.0",\n        status="rejected",\n    )\n''',
)
replace(
    "tests/test_pipeline_runs.py",
    '''    _record_call(\n        ledger, run_id=other_run_id, model="leak", prompt_id="other", prompt_version="9.9.9", input_tokens=100\n    )\n''',
    '''    _record_call(\n        ledger,\n        run_id=other_run_id,\n        model="leak",\n        prompt_id="other",\n        prompt_version="9.9.9",\n        input_tokens=100,\n    )\n''',
)
replace(
    "tests/test_pipeline_runs.py",
    '''    assert summary.prompt_versions == [\n        "reviewer@1.1.0",\n        "writer@1.0.0",\n    ]\n''',
    '''    assert summary.prompt_versions == [\n        "failed@1.0.0",\n        "rejected@1.0.0",\n        "reviewer@1.1.0",\n        "writer@1.0.0",\n    ]\n''',
)
