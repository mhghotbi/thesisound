from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import Script
from thesisound.script import (
    Glossary,
    ScriptCheckReport,
    ScriptPipelineManifest,
    SegmentScriptDraft,
    VerificationDraft,
)


class ScriptArtifactStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def script_dir(self, project_id: UUID) -> Path:
        path = self.workspace_root / str(project_id) / "script"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_glossary(self, glossary: Glossary) -> None:
        self._write_json(self.script_dir(glossary.project_id) / "glossary.json", glossary)

    def load_glossary(self, project_id: UUID) -> Glossary:
        return Glossary.model_validate_json(
            (self.script_dir(project_id) / "glossary.json").read_text(encoding="utf-8")
        )

    def save_segment_draft(
        self,
        project_id: UUID,
        segment_id: str,
        draft: SegmentScriptDraft,
    ) -> None:
        self._write_json(
            self.script_dir(project_id) / "segments" / f"{segment_id}.json",
            draft,
        )

    def save_script(self, project_id: UUID, script: Script, *, revised: bool = False) -> None:
        name = "script-revised.json" if revised else "script-draft.json"
        self._write_json(self.script_dir(project_id) / name, script)

    def load_script(self, project_id: UUID, *, revised: bool = False) -> Script:
        name = "script-revised.json" if revised else "script-draft.json"
        return Script.model_validate_json(
            (self.script_dir(project_id) / name).read_text(encoding="utf-8")
        )

    def save_checks(self, report: ScriptCheckReport, *, revised: bool = False) -> None:
        name = "checks-revised.json" if revised else "checks.json"
        self._write_json(self.script_dir(report.project_id) / name, report)

    def load_checks(self, project_id: UUID, *, revised: bool = False) -> ScriptCheckReport:
        name = "checks-revised.json" if revised else "checks.json"
        return ScriptCheckReport.model_validate_json(
            (self.script_dir(project_id) / name).read_text(encoding="utf-8")
        )

    def save_verification(
        self,
        project_id: UUID,
        report: VerificationDraft,
        *,
        revised: bool = False,
    ) -> None:
        name = "verification-revised.json" if revised else "verification.json"
        self._write_json(self.script_dir(project_id) / name, report)

    def load_verification(
        self,
        project_id: UUID,
        *,
        revised: bool = False,
    ) -> VerificationDraft:
        name = "verification-revised.json" if revised else "verification.json"
        return VerificationDraft.model_validate_json(
            (self.script_dir(project_id) / name).read_text(encoding="utf-8")
        )

    def save_manifest(self, manifest: ScriptPipelineManifest) -> None:
        self._write_json(
            self.script_dir(manifest.project_id) / "manifest.json",
            manifest,
        )

    def load_manifest(self, project_id: UUID) -> ScriptPipelineManifest:
        return ScriptPipelineManifest.model_validate_json(
            (self.script_dir(project_id) / "manifest.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def _write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        payload: Any = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
