from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import Script
from thesisound.script import (
    AbsorbedFault,
    AbsorbedFaultsLedger,
    Glossary,
    ProseLessonDraft,
    QualityNote,
    QualityNotesLedger,
    RevisionDecision,
    ScriptCheckReport,
    ScriptPipelineManifest,
    ScriptReviewDecision,
    SegmentScriptDraft,
    VerificationDraft,
)
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.semantic_identity import first_mismatch, script_pipeline_key


class ScriptArtifactStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def script_dir(self, project_id: UUID, *, create: bool = True) -> Path:
        path = self.workspace_root / str(project_id) / "script"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def part_script_dir(self, project_id: UUID, part_index: int, *, create: bool = True) -> Path:
        path = self.script_dir(project_id, create=create) / "parts" / str(part_index)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def plan_binding_path(self, project_id: UUID) -> Path:
        return self.script_dir(project_id, create=False) / "approved-plan-hash.txt"

    def pipeline_binding_path(self, project_id: UUID) -> Path:
        return self.script_dir(project_id, create=False) / "pipeline-binding.json"

    def clear_pipeline_artifacts(self, project_id: UUID) -> None:
        path = self.workspace_root / str(project_id) / "script"
        if path.exists():
            shutil.rmtree(path)

    def invalidate_from_stage(self, project_id: UUID, stage: str) -> list[str]:
        """Delete artifacts owned by ``stage`` and every later stage.

        Preserves plan/pipeline bindings so a scoped retry can resume upstream
        work (glossary, segment drafts, …) without a full wipe.
        """

        stage_order = (
            "building_glossary",
            "writing_segments",
            "checking_draft",
            "verifying_draft",
            "revising",
            "checking_revision",
            "verifying_revision",
        )
        artifacts_by_stage: dict[str, tuple[str, ...]] = {
            "building_glossary": ("glossary.json",),
            # Deliberately NOT "segments": each segment draft depends only on
            # the (unchanging) brief, segment, evidence pack, and glossary --
            # never on a sibling segment's outcome -- so a retry from this
            # stage can resume mid-script instead of re-writing and re-paying
            # for every already-succeeded segment. write_script() already
            # checks load_segment_draft_optional() per segment; this used to
            # defeat that by wiping the cache on every single retry.
            "writing_segments": (
                "script-draft.json",
                "speaker-balance-violations.json",
            ),
            "checking_draft": ("checks.json",),
            "verifying_draft": ("verification.json",),
            "revising": ("script-revised.json",),
            "checking_revision": ("checks-revised.json",),
            "verifying_revision": (
                "verification-revised.json",
                "revision-decision.json",
            ),
        }
        if stage not in artifacts_by_stage:
            raise ValueError(f"Unknown script pipeline stage for invalidation: {stage}")
        start = stage_order.index(stage)
        directory = self.script_dir(project_id, create=False)
        removed: list[str] = []
        if not directory.exists():
            return removed
        for name in stage_order[start:]:
            for relative in artifacts_by_stage[name]:
                path = directory / relative
                if not path.exists():
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(relative)
        return removed

    def prepare_for_plan(self, project_id: UUID, plan_hash: str) -> None:
        """Discard artifacts unless they belong to the exact approved plan."""

        directory = self.script_dir(project_id, create=False)
        if directory.exists() and not self.artifacts_match_plan(project_id, plan_hash):
            self.clear_pipeline_artifacts(project_id)
        binding = self.script_dir(project_id) / "approved-plan-hash.txt"
        _atomic_write_text(binding, plan_hash + "\n")

    def prepare_for_pipeline(
        self,
        project_id: UUID,
        plan_hash: str,
        identity: dict[str, Any],
    ) -> bool:
        """Bind script artifacts to plan hash plus model/prompt/checker identity.

        Returns True when existing artifacts already match (reuse hit). A miss wipes
        the script directory so glossary/drafts/checks cannot survive a semantic bump.
        """

        key = script_pipeline_key(plan_hash, identity)
        directory = self.script_dir(project_id, create=False)
        if directory.exists():
            reason = self._pipeline_mismatch_reason(project_id, plan_hash, identity, key)
            if reason is None:
                emit_cache_lookup(
                    cache="script_pipeline",
                    result="hit",
                    project_id=project_id,
                    lookup_key=key[:16],
                    avoided_calls=1,
                )
                return True
            emit_cache_lookup(
                cache="script_pipeline",
                result="miss",
                project_id=project_id,
                lookup_key=key[:16],
                invalidation_reason=reason,
            )
            self.clear_pipeline_artifacts(project_id)
        else:
            emit_cache_lookup(
                cache="script_pipeline",
                result="miss",
                project_id=project_id,
                lookup_key=key[:16],
                invalidation_reason="artifact_missing",
            )

        self.prepare_for_plan(project_id, plan_hash)
        payload = {
            "plan_hash": plan_hash,
            "pipeline_key": key,
            "identity": identity,
        }
        self._write_json(self.script_dir(project_id) / "pipeline-binding.json", payload)
        return False

    def artifacts_match_plan(self, project_id: UUID, plan_hash: str) -> bool:
        path = self.plan_binding_path(project_id)
        if not path.exists():
            return False
        return path.read_text(encoding="utf-8").strip() == plan_hash

    def artifacts_match_pipeline(
        self,
        project_id: UUID,
        plan_hash: str,
        identity: dict[str, Any],
    ) -> bool:
        key = script_pipeline_key(plan_hash, identity)
        return self._pipeline_mismatch_reason(project_id, plan_hash, identity, key) is None

    def _pipeline_mismatch_reason(
        self,
        project_id: UUID,
        plan_hash: str,
        identity: dict[str, Any],
        key: str,
    ) -> str | None:
        if not self.artifacts_match_plan(project_id, plan_hash):
            return "plan_hash_mismatch"
        path = self.pipeline_binding_path(project_id)
        if not path.exists():
            return "identity_missing"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return "identity_missing"
        stored_identity = payload.get("identity")
        if not isinstance(stored_identity, dict):
            return "identity_missing"
        if payload.get("pipeline_key") == key and payload.get("plan_hash") == plan_hash:
            return None
        fields = (
            "glossary_model",
            "glossary_prompt_version",
            "writer_model",
            "writer_prompt_version",
            "verifier_model",
            "verifier_prompt_version",
            "reviser_model",
            "reviser_prompt_version",
            "checker_version",
        )
        return first_mismatch(stored_identity, identity, fields) or "pipeline_key_mismatch"

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

    def save_part_script(self, project_id: UUID, part_index: int, script: Script) -> None:
        """A read-only, per-part slice of the verified script (`10c` P3 Step 9).

        Derived, not authoritative: the whole-project `script-draft.json` /
        `script-revised.json` (checked, verified, possibly revised as one
        unit) remains the source of truth. This is a materialized view for
        the parts list and per-part delivery, not a separate pipeline stage.
        """

        self._write_json(self.part_script_dir(project_id, part_index) / "script.json", script)

    def load_part_script(self, project_id: UUID, part_index: int) -> Script:
        path = self.part_script_dir(project_id, part_index, create=False) / "script.json"
        return Script.model_validate_json(path.read_text(encoding="utf-8"))

    def list_part_scripts(self, project_id: UUID) -> list[int]:
        parts_dir = self.script_dir(project_id, create=False) / "parts"
        if not parts_dir.exists():
            return []
        return sorted(
            int(child.name)
            for child in parts_dir.iterdir()
            if child.is_dir() and child.name.isdigit() and (child / "script.json").exists()
        )

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

    def prose_dir(self, project_id: UUID, *, create: bool = True) -> Path:
        path = self.script_dir(project_id, create=create) / "prose"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def save_prose_segment_draft(
        self,
        project_id: UUID,
        segment_id: str,
        draft: ProseLessonDraft,
    ) -> None:
        self._write_json(self.prose_dir(project_id) / "segments" / f"{segment_id}.json", draft)

    def load_prose_segment_draft_optional(
        self,
        project_id: UUID,
        segment_id: str,
    ) -> ProseLessonDraft | None:
        path = self.prose_dir(project_id, create=False) / "segments" / f"{segment_id}.json"
        try:
            return ProseLessonDraft.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_prose_script(self, project_id: UUID, script: Script) -> None:
        """The `delivery == both` written-lesson supplement (`10c` P4).

        For `delivery == text`, the prose IS the script (`script-draft.json`,
        via `save_script`); this method only exists for `both`, where a
        dialogue script is the primary artifact and prose is written
        alongside it from the same evidence, without a second full
        check/verify/revise cycle (see `ScriptPipelineService.run`).
        """

        self._write_json(self.prose_dir(project_id) / "lesson.json", script)

    def load_prose_script_optional(self, project_id: UUID) -> Script | None:
        path = self.prose_dir(project_id, create=False) / "lesson.json"
        try:
            return Script.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def part_prose_dir(self, project_id: UUID, part_index: int, *, create: bool = True) -> Path:
        path = self.prose_dir(project_id, create=create) / "parts" / str(part_index)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def save_part_prose_script(self, project_id: UUID, part_index: int, script: Script) -> None:
        self._write_json(self.part_prose_dir(project_id, part_index) / "lesson.json", script)

    def load_part_prose_script(self, project_id: UUID, part_index: int) -> Script:
        path = self.part_prose_dir(project_id, part_index, create=False) / "lesson.json"
        return Script.model_validate_json(path.read_text(encoding="utf-8"))

    def load_part_prose_script_optional(self, project_id: UUID, part_index: int) -> Script | None:
        try:
            return self.load_part_prose_script(project_id, part_index)
        except FileNotFoundError:
            return None

    def list_part_prose_scripts(self, project_id: UUID) -> list[int]:
        parts_dir = self.prose_dir(project_id, create=False) / "parts"
        if not parts_dir.exists():
            return []
        return sorted(
            int(child.name)
            for child in parts_dir.iterdir()
            if child.is_dir() and child.name.isdigit() and (child / "lesson.json").exists()
        )

    def save_quality_notes(self, ledger: QualityNotesLedger) -> None:
        self._write_json(
            self.script_dir(ledger.project_id) / "quality-notes.json",
            ledger,
        )

    def load_quality_notes_optional(self, project_id: UUID) -> QualityNotesLedger | None:
        path = self.script_dir(project_id, create=False) / "quality-notes.json"
        try:
            return QualityNotesLedger.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def append_quality_notes(
        self, project_id: UUID, notes: list[QualityNote]
    ) -> QualityNotesLedger:
        if not notes:
            existing = self.load_quality_notes_optional(project_id)
            return existing or QualityNotesLedger(project_id=project_id, notes=[])
        existing = self.load_quality_notes_optional(project_id)
        merged = QualityNotesLedger(
            project_id=project_id,
            notes=[*(existing.notes if existing is not None else []), *notes],
        )
        self.save_quality_notes(merged)
        return merged

    def replace_quality_notes(
        self, project_id: UUID, notes: list[QualityNote]
    ) -> QualityNotesLedger:
        ledger = QualityNotesLedger(project_id=project_id, notes=list(notes))
        self.save_quality_notes(ledger)
        return ledger

    def save_absorbed_faults(self, ledger: AbsorbedFaultsLedger) -> None:
        self._write_json(
            self.script_dir(ledger.project_id) / "absorbed-faults.json",
            ledger,
        )

    def load_absorbed_faults_optional(self, project_id: UUID) -> AbsorbedFaultsLedger | None:
        path = self.script_dir(project_id, create=False) / "absorbed-faults.json"
        try:
            return AbsorbedFaultsLedger.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def replace_absorbed_faults(
        self,
        project_id: UUID,
        faults: list[AbsorbedFault],
        *,
        substantive_turn_count: int = 0,
    ) -> AbsorbedFaultsLedger:
        ledger = AbsorbedFaultsLedger(
            project_id=project_id,
            faults=list(faults),
            substantive_turn_count=substantive_turn_count,
        )
        self.save_absorbed_faults(ledger)
        return ledger

    def append_absorbed_faults(
        self,
        project_id: UUID,
        faults: list[AbsorbedFault],
        *,
        substantive_turn_count: int | None = None,
    ) -> AbsorbedFaultsLedger:
        existing = self.load_absorbed_faults_optional(project_id)
        merged = AbsorbedFaultsLedger(
            project_id=project_id,
            faults=[*(existing.faults if existing is not None else []), *faults],
            substantive_turn_count=(
                substantive_turn_count
                if substantive_turn_count is not None
                else (existing.substantive_turn_count if existing is not None else 0)
            ),
        )
        self.save_absorbed_faults(merged)
        return merged

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

        ledger = self.load_quality_notes_optional(project_id)
        notes = ledger.notes if ledger is not None else []
        outcome, _ = script_outcome(checks, verification, quality_notes=notes)
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
