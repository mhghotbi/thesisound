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
