from pathlib import Path

path = Path(".github/align_observability_plan.py")
text = path.read_text(encoding="utf-8")

old = '''replace_once(OBS, "        error_message=row[16],", "        error_message=redact_exception_message(row[16]),")
# The span row has another error_message at index 16; replace the remaining occurrence.
replace_once(OBS, "        error_message=row[16],", "        error_message=redact_exception_message(row[16]),")'''
new = '''replace_all(
    OBS,
    "        error_message=row[16],",
    "        error_message=redact_exception_message(row[16]),",
    expected=2,
)'''
if text.count(old) != 1:
    raise RuntimeError("duplicate error-message patcher guard did not match exactly once")
text = text.replace(old, new, 1)

marker = '''# Ensure the old rollup API is gone from the ledger and all source callers use
# the dedicated service.'''
addition = '''EVAL_HARNESS = "src/thesisound/services/eval_harness.py"
replace_once(
    EVAL_HARNESS,
    "from thesisound.observability import ObservabilityLedger, tracer_from_settings\\n",
    "from thesisound.observability import ObservabilityLedger, tracer_from_settings\\nfrom thesisound.services.observability_rollup import ObservabilityRollup\\n",
)
replace_once(
    EVAL_HARNESS,
    "    usage = ledger.project_summary(project.project_id)\\n",
    "    usage = ObservabilityRollup(ledger).project_summary(project.project_id)\\n",
)

'''
if text.count(marker) != 1:
    raise RuntimeError("rollup caller insertion marker did not match exactly once")
text = text.replace(marker, addition + marker, 1)
path.write_text(text, encoding="utf-8")
