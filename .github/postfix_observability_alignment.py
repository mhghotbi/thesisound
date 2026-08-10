import re
from pathlib import Path

path = Path("src/thesisound/observability.py")
text = path.read_text(encoding="utf-8")
old = (
    "def _filename_identity(value: Any, container: Mapping[str, Any]) -> dict[str, Any]:\n"
    "    filename = str(value)\n"
)
new = (
    "def _filename_identity(value: Any, container: Mapping[str, Any]) -> dict[str, Any]:\n"
    "    if isinstance(value, Mapping):\n"
    "        digest = value.get(\"filename_sha256\")\n"
    "        extension = value.get(\"extension\")\n"
    "        if isinstance(digest, str) and isinstance(extension, str):\n"
    "            identity: dict[str, Any] = {\n"
    "                \"filename_sha256\": digest[:16],\n"
    "                \"extension\": extension,\n"
    "            }\n"
    "            size = value.get(\"size_bytes\")\n"
    "            if isinstance(size, int | float) and size >= 0:\n"
    "                identity[\"size_bytes\"] = int(size)\n"
    "            return identity\n"
    "\n"
    "    filename = str(value)\n"
)
if text.count(old) != 1:
    raise RuntimeError(f"filename identity insertion count={text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

path = Path("src/thesisound/logging_setup.py")
text = path.read_text(encoding="utf-8")
text, import_count = re.subn(
    r"from thesisound\.observability import is_sensitive_key, redact_text, redact_value",
    "from thesisound.observability import redact_text, redact_value",
    text,
    count=1,
)
loop_pattern = re.compile(
    r'''        for key, value in list\(record\.__dict__\.items\(\)\):\n'''
    r'''            if key in _STANDARD_LOG_RECORD_ATTRS:\n'''
    r'''                continue\n'''
    r'''(?:            #.*\n)*'''
    r'''            record\.__dict__\[key\] = \(\n'''
    r'''                "\[REDACTED\]"\n'''
    r'''                if is_sensitive_key\(key\)\n'''
    r'''                else redact_value\(value, store_payloads=self\.store_payloads\)\n'''
    r'''            \)\n'''
)
replacement = (
    "        extras = {\n"
    "            key: value\n"
    "            for key, value in record.__dict__.items()\n"
    "            if key not in _STANDARD_LOG_RECORD_ATTRS\n"
    "        }\n"
    "        redacted_extras = redact_value(extras, store_payloads=self.store_payloads)\n"
    "        for key, value in redacted_extras.items():\n"
    "            record.__dict__[key] = value\n"
)
text, block_count = loop_pattern.subn(replacement, text, count=1)
if import_count != 1 or block_count != 1:
    raise RuntimeError(
        f"logging central-redactor rewrite import={import_count} block={block_count}"
    )
path.write_text(text, encoding="utf-8")

path = Path("tests/test_observability_rollups.py")
text = path.read_text(encoding="utf-8")
text, span_count = re.subn(
    r'(        kind="stage",\n)(        started_at=started,)',
    r'\1        subject_type=None,\n        subject_id=None,\n\2',
    text,
    count=1,
)
text, event_count = re.subn(
    r'(                project_id=project_id,\n)(                occurred_at=)',
    r'\1                workflow_run_id=None,\n                level="info",\n                subject_type=None,\n                subject_id=None,\n\2',
    text,
    count=1,
)
if span_count != 1 or event_count != 1:
    raise RuntimeError(
        f"rollup record fixture fixes span={span_count} event={event_count}"
    )
path.write_text(text, encoding="utf-8")
