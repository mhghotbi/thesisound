from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
helper = ROOT / ".github" / "scripts" / "apply_server_mono_light.py"
source = helper.read_text(encoding="utf-8")
old = '''    "    ScriptPipelineResult,\\n",\n    "    ScriptPipelineResult,\\n    ScriptQualityScore,\\n",\n'''
new = '''    "    RevisedTurnDraft,\\n",\n    "    RevisedTurnDraft,\\n    ScriptQualityScore,\\n",\n'''
if old not in source:
    raise RuntimeError("The item 3 import-anchor patch no longer matches the staged helper.")
source = source.replace(old, new, 1)
exec(compile(source, str(helper), "exec"), {"__name__": "__main__", "__file__": str(helper)})

test_path = ROOT / "tests" / "test_script_quality.py"
test_source = test_path.read_text(encoding="utf-8")
test_source = test_source.replace("from uuid import uuid4\n\n", "", 1)
test_path.write_text(test_source, encoding="utf-8")
