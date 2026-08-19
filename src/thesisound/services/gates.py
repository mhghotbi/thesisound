from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GateActor = Literal["machine", "human"]


@dataclass(frozen=True, slots=True)
class GateDefinition:
    code: str
    order: int
    label_en: str
    actor: GateActor
    enforced_at: str
    reads: str
    writes: str
    blocked_means: str
    # Human + blocking on the build path is the stop budget (spec 12 D1).
    blocking: bool = True


GATE_REGISTRY: tuple[GateDefinition, ...] = (
    GateDefinition(
        "brief-confirmed",
        1,
        "Brief confirmed",
        "human",
        "src/thesisound/web/app.py:886",
        "Project brief",
        "SOURCES_COLLECTING state",
        "The operator has not submitted the project brief (topic and, optionally, scope).",
        blocking=False,
    ),
    GateDefinition(
        "source-selection-confirmed",
        2,
        "Source selection confirmed",
        "human",
        "src/thesisound/web/source_routes.py:738",
        "Selected source manifest",
        "CORPUS_BUILDING state and queued corpus run",
        "The operator has not confirmed the source set.",
        blocking=True,
    ),
    GateDefinition(
        "parse-quality",
        3,
        "Parse quality",
        "machine",
        "src/thesisound/services/parse_quality.py:27",
        "Parsed documents",
        "Parse-quality verdicts",
        "At least one selected source is unsafe for claim extraction.",
    ),
    GateDefinition(
        "evidence-validation",
        4,
        "Excerpt and evidence validation",
        "machine",
        "src/thesisound/services/evidence_validator.py:55",
        "Block extractions and source text",
        "Validated evidence items",
        "Quoted support cannot be matched or validated.",
    ),
    GateDefinition(
        "evidence-retention",
        5,
        "Evidence retention",
        "machine",
        "src/thesisound/services/source_analysis_service.py:65",
        "Extraction plan and block outcomes",
        "Source-analysis manifest",
        (
            "Less than 85% of planned token mass survived extraction, even after "
            "forgiving the largest single lost block."
        ),
    ),
    GateDefinition(
        "coverage-duration",
        6,
        "Coverage and supported duration",
        "machine",
        "src/thesisound/services/coverage_auditor.py:13",
        "Coverage report and current brief",
        "Episode-planning eligibility",
        "Coverage cannot support at least 80% of the requested duration.",
    ),
    GateDefinition(
        "episode-plan-approval",
        7,
        "Episode Plan approval",
        "human",
        "src/thesisound/services/plan_approval.py:81",
        "Episode Plan",
        "Named approval bound to plan hash",
        "The plan is unapproved or changed after approval.",
        blocking=True,
    ),
    GateDefinition(
        "script-checks",
        8,
        "Deterministic script checks",
        "machine",
        "src/thesisound/services/script_checks.py:108",
        "Script, plan, evidence packs and glossary",
        "Script check report",
        "A deterministic blocking violation exists.",
    ),
    GateDefinition(
        "independent-verification",
        9,
        "Independent verification",
        "machine",
        "src/thesisound/services/script_verifier.py:16",
        "Script and evidence packs",
        "Verification report",
        "Claims remain unsupported or verification did not pass.",
    ),
    GateDefinition(
        "script-review-decision",
        10,
        "Script review decision",
        "human",
        "src/thesisound/web/audio_routes.py:100",
        "Review-required script artifacts",
        "Named review decision",
        "A review-required script has no accepted human decision.",
        blocking=False,
    ),
    GateDefinition(
        "audio-start",
        11,
        "Audio start",
        "human",
        "src/thesisound/web/audio_routes.py:100",
        "Verified or review-accepted script",
        "Queued audio build run",
        "The operator has not started audio generation.",
        blocking=True,
    ),
    GateDefinition(
        "audio-qa",
        12,
        "Audio QA",
        "machine",
        "src/thesisound/services/audio_pipeline_service.py:193",
        "Audio QA report",
        "Accepted audio manifest",
        "Audio QA failed and no manual-review escape was used.",
    ),
    GateDefinition(
        "final-listen",
        13,
        "Final listen",
        "human",
        "unenforced",
        "Final assembled audio",
        "Operator release decision",
        "No human final-listen confirmation exists; this is a known gap.",
        blocking=False,
    ),
)
