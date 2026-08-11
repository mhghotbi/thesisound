from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import Script
from thesisound.script import (
    Glossary,
    RevisionDecision,
    ScriptCheckReport,
    ScriptPipelineManifest,
    ScriptReviewDecision,
    SegmentScriptDraft,
    VerificationDraft,
)


class ScriptArtifactStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def script_dir(self, project_id: UUID, *, create: bool = True) -> Path:
        path = self.workspace_root / str(project_id) / "script"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def plan_binding_path(self, project_id: UUID) -> Path:
        return self.script_dir(project_id, create=False) / "approved-plan-hash.txt"

    def clear_pipeline_artifacts(self, project_id: UUID) -> None:
        path = self.workspace_root / str(project_id) / "script"
        if path.exists():
            shutil.rmtree(path)

    def prepare_for_plan(self, project_id: UUID, plan_hash: str) -> None:
        """Discard artifacts unless they belong to the exact approved plan."""

        directory = self.script_dir(project_id, create=False)
        if directory.exists() and not self.artifacts_match_plan(project_id, plan_hash):
            self.clear_pipeline_artifacts(project_id)
        binding = self.script_dir(project_id) / "approved-plan-hash.txt"
        _atomic_write_text(binding, plan_hash + "\n")

    def artifacts_match_plan(self, project_id: UUID, plan_hash: str) -> bool:
        path = self.plan_binding_path(project_id)
        if not path.exists():
            return False
        return path.read_text(encoding="utf-8").strip() == plan_hash

    def require_plan(self, project_id: UUID, plan_hash: str) -> ScriptPipelineManifest:
        if not self.artifacts_match_plan(project_id, plan_hash):
            raise ValueError("Script artifacts belong to a different Episode Plan.")
        return self.load_manifest(project_id)

    def save_glossary(self, glossary: Glossary) -> None:
        self._write_json(self.script_dir(glossary.project_id) / "glossary.json", glossary)

    def load_glossary(self, project_id: UUID) -> Glossary:
        return Glossary.model_validate_json(
            (self.script_dir(project_id, create=False) / "glossary.json").read_text(
                encoding="utf-8"
            )
        )

    def load_glossary_optional(self, project_id: UUID) -> Glossary | None:
        try:
            glossary = self.load_glossary(project_id)
            self.load_manifest(project_id)
            return glossary
        except FileNotFoundError:
            return None

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

    def load_segment_draft(
        self,
        project_id: UUID,
        segment_id: str,
    ) -> SegmentScriptDraft:
        path = self.script_dir(project_id, create=False) / "segments" / f"{segment_id}.json"
        return SegmentScriptDraft.model_validate_json(path.read_text(encoding="utf-8"))

    def load_segment_draft_optional(
        self,
        project_id: UUID,
        segment_id: str,
    ) -> SegmentScriptDraft | None:
        try:
            return self.load_segment_draft(project_id, segment_id)
        except FileNotFoundError:
            return None

    def save_speaker_balance_violations(
        self,
        project_id: UUID,
        violations: dict[str, list[str]],
    ) -> None:
        self._write_json(
            self.script_dir(project_id) / "speaker-balance-violations.json",
            violations,
        )

    def load_speaker_balance_violations(self, project_id: UUID) -> dict[str, list[str]]:
        path = self.script_dir(project_id, create=False) / "speaker-balance-violations.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not all(
            isinstance(key, str)
            and isinstance(value, list)
            and all(isinstance(item, str) for item in value)
            for key, value in payload.items()
        ):
            raise ValueError("Speaker-balance violations artifact is invalid.")
        return payload

    def load_speaker_balance_violations_optional(
        self,
        project_id: UUID,
    ) -> dict[str, list[str]]:
        try:
            return self.load_speaker_balance_violations(project_id)
        except FileNotFoundError:
            return {}

    def save_script(self, project_id: UUID, script: Script, *, revised: bool = False) -> None:
        name = "script-revised.json" if revised else "script-draft.json"
        self._write_json(self.script_dir(project_id) / name, script)

    def load_script(self, project_id: UUID, *, revised: bool = False) -> Script:
        name = "script-revised.json" if revised else "script-draft.json"
        return Script.model_validate_json(
            (self.script_dir(project_id, create=False) / name).read_text(encoding="utf-8")
        )

    def load_script_optional(
        self,
        project_id: UUID,
        *,
        revised: bool = False,
    ) -> Script | None:
        try:
            return self.load_script(project_id, revised=revised)
        except FileNotFoundError:
            return None

    def save_revision_decision(self, decision: RevisionDecision) -> None:
        self._write_json(
            self.script_dir(decision.project_id) / "revision-decision.json",
            decision,
        )

    def load_revision_decision_optional(self, project_id: UUID) -> RevisionDecision | None:
        path = self.script_dir(project_id, create=False) / "revision-decision.json"
        try:
            return RevisionDecision.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_review_decision(self, decision: ScriptReviewDecision) -> None:
        self._write_json(self.script_dir(decision.project_id) / "review-decision.json", decision)

    def load_review_decision_optional(self, project_id: UUID) -> ScriptReviewDecision | None:
        path = self.script_dir(project_id, create=False) / "review-decision.json"
        try:
            return ScriptReviewDecision.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def has_revised_script(self, project_id: UUID) -> bool:
        if not (self.script_dir(project_id, create=False) / "script-revised.json").exists():
            return False
        decision = self.load_revision_decision_optional(project_id)
        # Artifacts written before revision decisions existed have no file; keep
        # the old "a revision exists, so use it" behaviour for them.
        return True if decision is None else decision.accepted

    def load_latest_script(self, project_id: UUID) -> Script:
        return self.load_script(project_id, revised=self.has_revised_script(project_id))

    def save_checks(self, report: ScriptCheckReport, *, revised: bool = False) -> None:
        name = "checks-revised.json" if revised else "checks.json"
        self._write_json(self.script_dir(report.project_id) / name, report)

    def load_checks(self, project_id: UUID, *, revised: bool = False) -> ScriptCheckReport:
        name = "checks-revised.json" if revised else "checks.json"
        return ScriptCheckReport.model_validate_json(
            (self.script_dir(project_id, create=False) / name).read_text(encoding="utf-8")
        )

    def load_checks_optional(
        self,
        project_id: UUID,
        *,
        revised: bool = False,
    ) -> ScriptCheckReport | None:
        try:
            return self.load_checks(project_id, revised=revised)
        except FileNotFoundError:
            return None

    def load_latest_checks(self, project_id: UUID) -> ScriptCheckReport:
        return self.load_checks(project_id, revised=self.has_revised_script(project_id))

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
            (self.script_dir(project_id, create=False) / name).read_text(encoding="utf-8")
        )

    def load_verification_optional(
        self,
        project_id: UUID,
        *,
        revised: bool = False,
    ) -> VerificationDraft | None:
        try:
            return self.load_verification(project_id, revised=revised)
        except FileNotFoundError:
            return None

    def load_latest_verification(self, project_id: UUID) -> VerificationDraft:
        return self.load_verification(
            project_id,
            revised=self.has_revised_script(project_id),
        )

    def save_manifest(self, manifest: ScriptPipelineManifest) -> None:
        self._write_json(
            self.script_dir(manifest.project_id) / "manifest.json",
            manifest,
        )

    def load_manifest(self, project_id: UUID) -> ScriptPipelineManifest:
        return ScriptPipelineManifest.model_validate_json(
            (self.script_dir(project_id, create=False) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def load_manifest_optional(self, project_id: UUID) -> ScriptPipelineManifest | None:
        return self._optional(self.load_manifest, project_id)

    def has_verified_artifacts(
        self,
        project_id: UUID,
        *,
        plan_hash: str | None = None,
    ) -> bool:
        expected_hash = plan_hash or self._current_run_plan_hash(project_id)
        if expected_hash is None or not self.artifacts_match_plan(project_id, expected_hash):
            return False
        try:
            checks = self.load_latest_checks(project_id)
            verification = self.load_latest_verification(project_id)
            manifest = self.load_manifest(project_id)
            self.load_latest_script(project_id)
        except FileNotFoundError:
            return False
        verified_normally = (
            checks.verdict == "pass"
            and verification.verdict == "pass"
            and verification.unsupported_claim_ratio == 0
            and manifest.status == "verified"
        )
        decision = self.load_review_decision_optional(project_id)
        accepted_under_review = bool(
            decision
            and decision.decision == "accepted"
            and decision.plan_hash == expected_hash
            and manifest.status == "verified"
        )
        return verified_normally or accepted_under_review

    def has_reviewable_artifacts(
        self,
        project_id: UUID,
        *,
        plan_hash: str,
    ) -> bool:
        """Whether a completed non-rejected pipeline result can await human review."""

        if not self.artifacts_match_plan(project_id, plan_hash):
            return False
        try:
            checks = self.load_latest_checks(project_id)
            verification = self.load_latest_verification(project_id)
            manifest = self.load_manifest(project_id)
            self.load_latest_script(project_id)
        except FileNotFoundError:
            return False
        from thesisound.services.script_outcome import script_outcome

        outcome, _ = script_outcome(checks, verification)
        return outcome == "review_required" and manifest.status == "review_required"

    def _current_run_plan_hash(self, project_id: UUID) -> str | None:
        path = self.workspace_root / str(project_id) / "script-build-run.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = payload.get("approved_plan_hash")
        return value if isinstance(value, str) else None

    @staticmethod
    def _optional(loader, project_id: UUID):
        try:
            return loader(project_id)
        except FileNotFoundError:
            return None

    @staticmethod
    def _write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
