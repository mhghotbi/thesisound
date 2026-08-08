from __future__ import annotations

from uuid import UUID

from thesisound.domain import EpisodePlan, Script
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, ScriptCheckReport, VerificationDraft
from thesisound.services.model_runner import ModelRunner


class ScriptVerifierService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def verify(
        self,
        *,
        project_id: UUID,
        script: Script,
        checks: ScriptCheckReport,
        episode_plan: EpisodePlan,
        evidence_packs: list[SegmentEvidencePack],
        glossary: Glossary,
        disagreement_graph: DisagreementGraph,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[VerificationDraft, ModelRunRecord]:
        known_turn_ids = {turn.turn_id for turn in script.turns}
        execution = self.model_runner.run(
            project_id=project_id,
            stage="script_verifier",
            prompt_name="script_verifier",
            variables={
                "script": script.model_dump(mode="json"),
                "deterministic_checks": checks.model_dump(mode="json"),
                "episode_plan": episode_plan.model_dump(mode="json"),
                "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
                "glossary": glossary.model_dump(mode="json"),
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
            },
            output_type=VerificationDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_verification(draft, known_turn_ids),
        )
        return execution.output, execution.record


def _validate_verification(
    draft: VerificationDraft,
    known_turn_ids: set[str],
) -> None:
    unknown = sorted({issue.turn_id for issue in draft.issues} - known_turn_ids)
    if unknown:
        raise DeterministicValidationError(
            "Verifier references unknown turn IDs: " + ", ".join(unknown)
        )
    if draft.verdict == "pass" and draft.issues:
        raise DeterministicValidationError("Passing verification may not contain issues.")
    unsupported_count = sum(
        issue.issue_type == "unsupported_claim" for issue in draft.issues
    )
    if unsupported_count == 0 and draft.unsupported_claim_ratio != 0:
        raise DeterministicValidationError(
            "Unsupported claim ratio must be zero when no unsupported claim issues exist."
        )
    if draft.verdict == "pass" and draft.unsupported_claim_ratio != 0:
        raise DeterministicValidationError(
            "Passing verification requires zero unsupported claim ratio."
        )
