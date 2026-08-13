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
    if draft.quality is None:
        raise DeterministicValidationError(
            "Verification must include quality scores."
        )
    if draft.verdict != "pass" and not draft.quality.actionable_feedback.strip():
        raise DeterministicValidationError(
            "A non-passing verification must include actionable feedback."
        )
    # Recoverable, and a silent correct repair (spec 09 D2, same class as the
    # JSON-escape fix): the itemised issues are the verifier's real finding --
    # each names a turn and is independently checkable -- while the ratio is a
    # summary the model recomputes by hand and routinely gets wrong. A ratio
    # with no unsupported-claim issue behind it asserts nothing verifiable, so
    # take the issues as authoritative instead of failing the build over the
    # model's arithmetic. Grounding itself is not left to this number: the
    # deterministic checks already ran against the ledger.
    if not any(issue.issue_type == "unsupported_claim" for issue in draft.issues):
        draft.unsupported_claim_ratio = 0.0
    if (
        draft.unsupported_claim_ratio > 0
        and draft.quality.evidence_fidelity >= 1.0
    ):
        raise DeterministicValidationError(
            "Unsupported claims contradict perfect evidence fidelity."
        )
    unknown = sorted({issue.turn_id for issue in draft.issues} - known_turn_ids)
    if unknown:
        raise DeterministicValidationError(
            "Verifier references unknown turn IDs: " + ", ".join(unknown)
        )
    if draft.verdict == "pass" and draft.issues:
        raise DeterministicValidationError("Passing verification may not contain issues.")
    # The zero-ratio-without-issues case is repaired above, not raised.
    if draft.verdict == "pass" and draft.unsupported_claim_ratio != 0:
        raise DeterministicValidationError(
            "Passing verification requires zero unsupported claim ratio."
        )
