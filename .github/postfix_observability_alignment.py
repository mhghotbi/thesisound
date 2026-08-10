from pathlib import Path
import re

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
text, block_count = re.subn(
    r'''            record\.__dict__\[key\] = \(\n                "\[REDACTED\]"\n                if is_sensitive_key\(key\)\n                else redact_value\(value, store_payloads=self\.store_payloads\)\n            \)''',
    "            record.__dict__[key] = redact_value(\n"
    "                {key: value}, store_payloads=self.store_payloads\n"
    "            )[key]",
    text,
    count=1,
)
if import_count != 1 or block_count != 1:
    raise RuntimeError(
        f"logging central-redactor rewrite import={import_count} block={block_count}"
    )
path.write_text(text, encoding="utf-8")

path = Path("tests/test_observability_rollups.py")
text = path.read_text(encoding="utf-8")
text, count = re.subn(
    r'(        kind="stage",\n)(        started_at=started,)',
    r'\1        subject_type=None,\n        subject_id=None,\n\2',
    text,
    count=1,
)
if count != 1:
    raise RuntimeError(f"rollup SpanRecord fix count={count}")
path.write_text(text, encoding="utf-8")
