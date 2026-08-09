from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Missing item 4 import anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


for path in (
    "src/thesisound/services/script_artifact_store.py",
    "src/thesisound/services/script_pipeline_service.py",
):
    replace(
        path,
        "    Glossary,\n    ScriptCheckReport,\n    RevisionDecision,\n",
        "    Glossary,\n    RevisionDecision,\n    ScriptCheckReport,\n",
    )

replace(
    "tests/test_script_quality.py",
    "from thesisound.script import (\n    ScriptCheckIssue,\n    ScriptCheckReport,\n    _QUALITY_WEIGHTS,\n",
    "from thesisound.script import (\n    _QUALITY_WEIGHTS,\n    ScriptCheckIssue,\n    ScriptCheckReport,\n",
)
