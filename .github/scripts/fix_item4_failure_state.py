from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "src" / "thesisound" / "services" / "script_pipeline_service.py"
text = path.read_text(encoding="utf-8")
old = '''        if project.state != ProjectState.FAILED_RETRYABLE:\n            mark_failed(project, message)\n        else:\n            project.last_error = message\n            project.updated_at = datetime.now(UTC)\n'''
new = '''        if project.state not in {\n            ProjectState.FAILED_RETRYABLE,\n            ProjectState.SCRIPT_READY,\n        }:\n            mark_failed(project, message)\n        else:\n            # SCRIPT_READY cannot transition directly to FAILED_RETRYABLE. Preserve\n            # the original pipeline error instead of masking it with a transition\n            # error; a resumed run can restore drafting from SCRIPT_READY.\n            project.last_error = message\n            project.updated_at = datetime.now(UTC)\n'''
if old not in text:
    if new in text:
        raise SystemExit(0)
    raise RuntimeError("Missing item 4 failure-state anchor")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
