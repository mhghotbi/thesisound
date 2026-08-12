from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from thesisound.audio import AudioPipelineManifest, script_hash
from thesisound.domain import Project, ProjectState
from thesisound.episode import CoverageReport
from thesisound.ingestion import IngestionResult
from thesisound.modeling import DeterministicValidationError
from thesisound.services.coverage_auditor import can_plan_episode
from thesisound.services.evidence_artifact_upgrade import (
    EvidenceArtifactUpgradeError,
    resolve_block_locator,
    upgrade_block_extraction_payload,
)
from thesisound.services.evidence_validator import validate_evidence_collection
from thesisound.services.gates import GATE_REGISTRY, GateActor
from thesisound.services.parse_quality import assess_parse_quality
from thesisound.services.plan_approval import EpisodePlanApproval, episode_plan_hash
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.source_analysis_service import (
    _MIN_PLANNED_TOKEN_RETENTION,
    _MIN_RETENTION_AFTER_LARGEST_LOSS,
    evidence_retention_holds,
)
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

GateStatus = Literal["pass", "blocked", "not_reached", "unknown"]
GateReason = Literal["schema", "io", "contract"]


@dataclass(frozen=True, slots=True)
class GateResult:
    code: str
    label: str
    actor: GateActor
    status: GateStatus
    detail: str
    evidence: str | None = None
    reason: GateReason | None = None


def project_readiness(*, project_id: UUID, workspace_root: Path) -> list[GateResult]:
    """Re-run project gates from stored inputs without writing any artifact."""

    root = workspace_root.expanduser().resolve()
    project_path = root / str(project_id) / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    definitions = {gate.code: gate for gate in GATE_REGISTRY}
    try:
        project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        detail = f"Project artifact is unreadable: {exc}"
        return [
            GateResult(
                code=gate.code,
                label=gate.label_en,
                actor=gate.actor,
                status="unknown",
                detail=detail,
                evidence=str(project_path),
                reason="io",
            )
            for gate in GATE_REGISTRY
        ]
    if project.state == ProjectState.DRAFT:
        return [
            GateResult(
                gate.code,
                gate.label_en,
                gate.actor,
                "not_reached",
                "The inputs for this gate do not exist yet.",
            )
            for gate in GATE_REGISTRY
        ]

    results: dict[str, GateResult] = {}

    def set_result(
        code: str,
        status: GateStatus,
        detail: str,
        evidence: Path | str | None = None,
        reason: GateReason | None = None,
    ) -> None:
        gate = definitions[code]
        results[code] = GateResult(
            code=code,
            label=gate.label_en,
            actor=gate.actor,
            status=status,
            detail=detail,
            evidence=str(evidence) if evidence is not None else None,
            reason=reason,
        )

    brief_path = root / str(project_id) / "project.json"
    if project.brief is None:
        set_result("brief-confirmed", "not_reached", "No ResearchBrief is stored.", brief_path)
    elif project.state == ProjectState.BRIEF_READY:
        set_result(
            "brief-confirmed",
            "blocked",
            "The stored brief still requires human confirmation.",
            brief_path,
        )
    else:
        set_result(
            "brief-confirmed", "pass", "The project proceeded from the confirmed brief.", brief_path
        )

    included = [source for source in project.sources if source.usable_as_evidence]
    if project.state in {ProjectState.BRIEF_READY, ProjectState.SOURCES_COLLECTING}:
        set_result(
            "source-selection-confirmed",
            "not_reached",
            "Source selection has not reached confirmation.",
            brief_path,
        )
    elif project.state == ProjectState.SOURCE_SELECTION_REQUIRED:
        set_result(
            "source-selection-confirmed",
            "blocked",
            "The selected source set requires human confirmation.",
            brief_path,
        )
    elif included or (root / str(project_id) / "sources").exists():
        set_result(
            "source-selection-confirmed",
            "pass",
            "The project proceeded with a confirmed corpus.",
            brief_path,
        )
    else:
        set_result(
            "source-selection-confirmed",
            "unknown",
            "The project state implies confirmation but no source artifacts were found.",
            brief_path,
        )

    source_root = root / str(project_id) / "sources"
    source_dirs = (
        sorted(path for path in source_root.glob("*") if path.is_dir())
        if source_root.exists()
        else []
    )
    if not source_dirs:
        for code in ("parse-quality", "evidence-validation", "evidence-retention"):
            set_result(code, "not_reached", "No source-analysis artifacts exist.")
    else:
        _parse_quality_results(source_dirs, set_result)
        _evidence_results(source_dirs, set_result)

    coverage_path = root / str(project_id) / "episode" / "coverage-report.json"
    if project.brief is None or not coverage_path.exists():
        set_result(
            "coverage-duration", "not_reached", "Coverage has not been audited.", coverage_path
        )
    else:
        try:
            coverage = CoverageReport.model_validate_json(coverage_path.read_text(encoding="utf-8"))
            allowed = can_plan_episode(
                recommendation=coverage.recommendation,
                max_supported_minutes=coverage.max_supported_minutes,
                target_duration_minutes=project.brief.target_duration_minutes,
            )
            set_result(
                "coverage-duration",
                "pass" if allowed else "blocked",
                (
                    f"Current request is {project.brief.target_duration_minutes} minutes; "
                    f"the audit supports {coverage.max_supported_minutes} minutes."
                ),
                coverage_path,
            )
        except (OSError, ValueError) as exc:
            set_result(
                "coverage-duration",
                "unknown",
                f"Coverage artifact is unreadable: {exc}",
                coverage_path,
            )

    approval_path = root / str(project_id) / "episode" / "plan-approval.json"
    if project.episode_plan is None:
        set_result("episode-plan-approval", "not_reached", "No Episode Plan exists.", approval_path)
    elif not approval_path.exists():
        set_result(
            "episode-plan-approval",
            "blocked",
            "The current Episode Plan has not been approved.",
            approval_path,
        )
    else:
        try:
            approval = EpisodePlanApproval.model_validate_json(
                approval_path.read_text(encoding="utf-8")
            )
            current_hash = episode_plan_hash(project.episode_plan)
            set_result(
                "episode-plan-approval",
                "pass" if approval.plan_hash == current_hash else "blocked",
                "Approval is bound to the current Episode Plan."
                if approval.plan_hash == current_hash
                else "The Episode Plan changed after approval.",
                approval_path,
            )
        except (OSError, ValueError) as exc:
            set_result(
                "episode-plan-approval",
                "unknown",
                f"Approval artifact is unreadable: {exc}",
                approval_path,
            )

    _script_results(project_id, root, project, set_result)
    _audio_results(project_id, root, set_result)

    if project.state == ProjectState.COMPLETE:
        set_result(
            "final-listen", "unknown", "A final listen is required but is not yet recorded in code."
        )
    else:
        set_result("final-listen", "not_reached", "Final audio is not ready for the human listen.")

    return [results[gate.code] for gate in GATE_REGISTRY]


def _parse_quality_results(source_dirs: list[Path], set_result) -> None:
    failures: list[str] = []
    read = 0
    try:
        for directory in source_dirs:
            path = directory / "ingestion-result.json"
            if not path.exists():
                continue
            ingestion = IngestionResult.model_validate_json(path.read_text(encoding="utf-8"))
            if ingestion.parsed is None:
                failures.append(f"{directory.name}: no parsed document")
                continue
            read += 1
            report = assess_parse_quality(ingestion.inspection, ingestion.parsed)
            if not report.safe_for_claim_extraction:
                failures.append(f"{directory.name}: {report.verdict}")
        if not read and not failures:
            set_result("parse-quality", "not_reached", "No parsed source artifact exists.")
        elif failures:
            set_result("parse-quality", "blocked", "; ".join(failures[:4]))
        else:
            set_result("parse-quality", "pass", f"Re-ran parse quality for {read} source(s).")
    except (OSError, ValueError) as exc:
        set_result("parse-quality", "unknown", f"A parse artifact is unreadable: {exc}")


def _evidence_results(source_dirs: list[Path], set_result) -> None:
    validation_failures: list[str] = []
    validated_sources = 0
    unreadable: list[tuple[str, str, GateReason, str]] = []
    retention_errors: list[str] = []
    retention_skipped_sources: list[str] = []
    planned_tokens = kept_tokens = largest_lost_tokens = 0
    plans = 0

    for directory in source_dirs:
        blocks_path = directory / "document-blocks.jsonl"
        plan_path = directory / "evidence-extraction-plan.json"
        extraction_dir = directory / "evidence" / "extractions"
        if not (blocks_path.exists() and extraction_dir.exists()):
            continue

        try:
            blocks = [
                SourceDocumentBlock.model_validate_json(line)
                for line in blocks_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
        except (OSError, ValueError) as exc:
            unreadable.append(
                (directory.name, blocks_path.name, "io", str(exc))
            )
            retention_skipped_sources.append(directory.name)
            continue

        block_locators = {block.block_id: block.locator for block in blocks}
        records: list[BlockEvidenceExtraction] = []
        source_unreadable = 0
        extraction_paths = sorted(extraction_dir.glob("*.json"))

        for path in extraction_paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                locator = resolve_block_locator(raw, block_locators)
                upgraded = upgrade_block_extraction_payload(
                    raw, block_locator=locator
                )
                records.append(BlockEvidenceExtraction.model_validate(upgraded))
            except EvidenceArtifactUpgradeError as exc:
                source_unreadable += 1
                unreadable.append((directory.name, path.name, "schema", str(exc)))
            except (OSError, UnicodeError) as exc:
                source_unreadable += 1
                unreadable.append((directory.name, path.name, "io", str(exc)))
            except (json.JSONDecodeError, ValidationError, ValueError, KeyError) as exc:
                source_unreadable += 1
                reason: GateReason = (
                    "schema"
                    if isinstance(exc, (ValidationError, json.JSONDecodeError))
                    else "contract"
                )
                unreadable.append((directory.name, path.name, reason, str(exc)))

        if source_unreadable:
            retention_skipped_sources.append(directory.name)

        if not records and source_unreadable:
            # Entirely unreadable: this source alone is unknown; others continue.
            continue

        extracted = [record for record in records if record.status == "extracted"]
        try:
            validate_evidence_collection(extracted, blocks)
        except DeterministicValidationError as exc:
            validation_failures.append(f"{directory.name}: {exc}")
        validated_sources += 1

        if source_unreadable:
            # Retention must not treat skipped artifacts as token loss.
            continue
        if not plan_path.exists():
            continue
        try:
            plan = EvidenceExtractionPlan.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
            by_id = {block.block_id: block for block in blocks}
            missing_block_ids = [
                block_id for block_id in plan.selected_block_ids if block_id not in by_id
            ]
            if missing_block_ids:
                missing = ", ".join(missing_block_ids[:4])
                raise ValueError(
                    f"Extraction plan references missing source block(s): {missing}"
                )
            planned = [by_id[block_id] for block_id in plan.selected_block_ids]
            kept_ids = {record.block_id for record in extracted}
            planned_tokens += sum(block.estimated_token_count for block in planned)
            kept_tokens += sum(
                block.estimated_token_count
                for block in planned
                if block.block_id in kept_ids
            )
            # One forgiven loss per source, so aggregating sources cannot make the
            # gate stricter than running it on each source on its own.
            largest_lost_tokens += max(
                (
                    block.estimated_token_count
                    for block in planned
                    if block.block_id not in kept_ids
                ),
                default=0,
            )
            plans += 1
        except (OSError, ValueError, KeyError) as exc:
            retention_errors.append(f"{directory.name}: {exc}")

    unread_labels = [f"{source}/{name}" for source, name, _, _ in unreadable]
    unread_detail = ""
    if unread_labels:
        shown = "; ".join(unread_labels[:4])
        extra = len(unread_labels) - 4
        unread_detail = (
            f" Unreadable artifact(s): {shown}"
            + (f" (+{extra} more)" if extra > 0 else "")
            + f" [{len(unread_labels)} total]."
        )

    if not validated_sources and unreadable:
        primary_reason = unreadable[0][2]
        set_result(
            "evidence-validation",
            "unknown",
            f"Evidence artifacts are unreadable.{unread_detail}".strip(),
            reason=primary_reason,
        )
    elif not validated_sources:
        set_result(
            "evidence-validation",
            "not_reached",
            "No extraction artifacts exist.",
        )
    else:
        detail = (
            "; ".join(validation_failures[:4])
            if validation_failures
            else f"Revalidated evidence for {validated_sources} source(s)."
        )
        if unread_detail and not validation_failures:
            detail = detail.rstrip(".") + "." + unread_detail
        elif unread_detail:
            detail = detail + unread_detail
        set_result(
            "evidence-validation",
            "blocked" if validation_failures else "pass",
            detail,
        )

    if retention_skipped_sources or unreadable:
        primary_reason = unreadable[0][2] if unreadable else "schema"
        set_result(
            "evidence-retention",
            "unknown",
            (
                "Retention cannot be scored while extraction artifacts are unreadable."
                + unread_detail
            ).strip(),
            reason=primary_reason,
        )
    elif retention_errors:
        set_result(
            "evidence-retention",
            "unknown",
            f"Retention inputs are unreadable: {'; '.join(retention_errors[:4])}",
            reason="contract",
        )
    elif not plans:
        set_result(
            "evidence-retention",
            "not_reached",
            "No completed extraction plan exists.",
        )
    else:
        retention = kept_tokens / planned_tokens if planned_tokens else 1.0
        holds = evidence_retention_holds(
            planned_tokens=planned_tokens,
            kept_tokens=kept_tokens,
            largest_lost_tokens=largest_lost_tokens,
        )
        set_result(
            "evidence-retention",
            "pass" if holds else "blocked",
            (
                f"Kept {retention:.0%} of planned token mass; minimum is "
                f"{_MIN_PLANNED_TOKEN_RETENTION:.0%} with the largest single loss per "
                f"source forgiven, never below {_MIN_RETENTION_AFTER_LARGEST_LOSS:.0%}."
            ),
        )


def _script_results(project_id: UUID, root: Path, project, set_result) -> None:
    store = ScriptArtifactStore(root)
    script_dir = root / str(project_id) / "script"
    script_codes = ("script-checks", "independent-verification", "script-review-decision")
    if not script_dir.exists():
        for code in script_codes:
            set_result(code, "not_reached", "Script artifacts do not exist.")
        return
    if project.episode_plan is None:
        for code in script_codes:
            set_result(
                code,
                "unknown",
                "Script artifacts exist but the Episode Plan is missing.",
                script_dir,
            )
        return

    current_hash = episode_plan_hash(project.episode_plan)
    try:
        if not store.artifacts_match_plan(project_id, current_hash):
            for code in script_codes:
                set_result(
                    code,
                    "blocked",
                    "Script artifacts are bound to a different Episode Plan.",
                    script_dir,
                )
            return
    except (OSError, ValueError) as exc:
        for code in script_codes:
            set_result(
                code,
                "unknown",
                f"Script plan binding is unreadable: {exc}",
                script_dir,
            )
        return

    artifact_set_error: str | None = None
    try:
        verified_artifacts = store.has_verified_artifacts(project_id, plan_hash=current_hash)
        reviewable_artifacts = (
            project.state == ProjectState.SCRIPT_REVIEW_REQUIRED
            and store.has_reviewable_artifacts(project_id, plan_hash=current_hash)
        )
    except (OSError, ValueError) as exc:
        verified_artifacts = False
        reviewable_artifacts = False
        artifact_set_error = str(exc)

    try:
        checks = store.load_latest_checks(project_id)
        set_result(
            "script-checks",
            "blocked"
            if checks.verdict == "reject"
            or any(item.severity == "blocking" for item in checks.issues)
            else "pass",
            f"Current deterministic verdict: {checks.verdict}.",
            script_dir,
        )
    except FileNotFoundError:
        set_result("script-checks", "not_reached", "Deterministic checks have not run.", script_dir)
    except (OSError, ValueError) as exc:
        set_result("script-checks", "unknown", f"Check report is unreadable: {exc}", script_dir)

    decision = None
    decision_error: str | None = None
    try:
        decision = store.load_review_decision_optional(project_id)
    except (OSError, ValueError) as exc:
        decision_error = str(exc)
    accepted_current_review = bool(
        decision and decision.decision == "accepted" and decision.plan_hash == current_hash
    )
    verified_normally = False
    try:
        verification = store.load_latest_verification(project_id)
        verified_normally = (
            verification.verdict == "pass" and verification.unsupported_claim_ratio == 0
        )
        if verified_normally:
            verification_status: GateStatus = "pass"
            detail = "The independent verifier passed with no unsupported claims."
        elif decision_error is not None:
            verification_status = "unknown"
            detail = f"Review decision is unreadable: {decision_error}"
        elif accepted_current_review:
            verification_status = "pass"
            detail = (
                "The verifier did not pass, but a named human accepted this exact "
                "plan-bound script."
            )
        else:
            verification_status = "blocked"
            detail = (
                f"Verifier verdict is {verification.verdict}; unsupported ratio is "
                f"{verification.unsupported_claim_ratio:.1%}."
            )
        set_result(
            "independent-verification",
            verification_status,
            detail,
            script_dir,
        )
    except FileNotFoundError:
        set_result(
            "independent-verification",
            "not_reached",
            "Independent verification has not run.",
            script_dir,
        )
    except (OSError, ValueError) as exc:
        set_result(
            "independent-verification",
            "unknown",
            f"Verification report is unreadable: {exc}",
            script_dir,
        )

    if decision_error is not None:
        set_result(
            "script-review-decision",
            "unknown",
            f"Review decision is unreadable: {decision_error}",
            script_dir / "review-decision.json",
        )
    elif project.state == ProjectState.SCRIPT_REVIEW_REQUIRED:
        set_result(
            "script-review-decision",
            "blocked",
            "A named reviewer must accept or send back this script.",
            script_dir,
        )
    elif decision is None:
        set_result(
            "script-review-decision",
            "not_reached",
            "No human script review was required.",
            script_dir,
        )
    else:
        accepted = decision.decision == "accepted" and decision.plan_hash == current_hash
        set_result(
            "script-review-decision",
            "pass" if accepted else "blocked",
            "The named review acceptance is bound to the current plan."
            if accepted
            else "The review decision is not an accepted decision for the current plan.",
            script_dir / "review-decision.json",
        )

    if project.state == ProjectState.SCRIPT_REVIEW_REQUIRED and not reviewable_artifacts:
        if artifact_set_error is not None and decision_error is None:
            set_result(
                "script-review-decision",
                "unknown",
                f"Reviewable script artifact set is unreadable: {artifact_set_error}",
                script_dir,
            )
        elif artifact_set_error is None and decision_error is None:
            set_result(
                "script-review-decision",
                "blocked",
                "Human review requires a complete current-plan reviewable script artifact set.",
                script_dir,
            )

    verified_state = project.state in {
        ProjectState.SCRIPT_VERIFIED,
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_READY,
        ProjectState.AUDIO_VERIFYING,
        ProjectState.COMPLETE,
    }
    if verified_state and not verified_artifacts:
        if artifact_set_error is not None:
            # A corrupt review decision is reported by its own human gate. When
            # the independent verifier already passed normally, do not let that
            # unrelated optional artifact erase the machine-verification result.
            if not (decision_error is not None and verified_normally):
                set_result(
                    "independent-verification",
                    "unknown",
                    f"Verified script artifact set is unreadable: {artifact_set_error}",
                    script_dir,
                )
        else:
            set_result(
                "independent-verification",
                "blocked",
                "The current state requires a complete current-plan verified script artifact set.",
                script_dir,
            )


def _audio_results(project_id: UUID, root: Path, set_result) -> None:
    path = root / str(project_id) / "audio" / "manifest.json"
    if not path.exists():
        set_result("audio-qa", "not_reached", "No audio QA manifest exists.", path)
        return
    try:
        manifest = AudioPipelineManifest.model_validate_json(path.read_text(encoding="utf-8"))
        script = ScriptArtifactStore(root).load_latest_script(project_id)
        bound = manifest.script_hash == script_hash(script)
        passed = bound and manifest.status == "verified"
        set_result(
            "audio-qa",
            "pass" if passed else "blocked",
            "Audio is verified and bound to the current script."
            if passed
            else "Audio is not verified or is bound to a stale script.",
            path,
        )
    except (OSError, ValueError) as exc:
        set_result("audio-qa", "unknown", f"Audio manifest is unreadable: {exc}", path)
