from __future__ import annotations

import json
import shutil
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from thesisound import tracing
from thesisound.config import Settings
from thesisound.domain import Project, ProjectState, ResearchBrief
from thesisound.episode_cli import _service as build_episode_service
from thesisound.observability import ObservabilityLedger, tracer_from_settings
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.script_cli import _service as build_script_service
from thesisound.services.observability_rollup import ObservabilityRollup
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_outcome import script_outcome
from thesisound.source_cli import _model_service as build_source_service
from thesisound.web.source_ingestion import ingest_uploaded_source

GateStatus = Literal["pass", "fail", "skipped"]
EvalSplit = Literal["core", "holdout"]


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    directory: Path
    brief: ResearchBrief
    sources: tuple[Path, ...]
    expectations: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CaseMetrics:
    case_id: str
    project_id: str
    checks_verdict: str
    verification_verdict: str
    unsupported_claim_ratio: float
    quality_overall: float | None
    script_outcome: str
    revision_accepted: bool | None
    revision_delta: float | None
    coverage_recommendation: str
    max_supported_minutes: int
    can_plan_episode: bool
    estimated_minutes: float
    skipped_block_count: int
    call_count: int
    failed_count: int
    total_tokens: int
    wall_clock_seconds: float
    cost_micros: int | None
    cost_is_partial: bool
    cost_micros_per_output_minute: int | None
    expectations: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    name: str
    status: GateStatus
    observed: float | int | None
    threshold: float | int | None
    comparison: str


@dataclass(frozen=True, slots=True)
class EvalReport:
    generated_at: str
    cases: tuple[CaseMetrics, ...]
    gates: tuple[GateEvaluation, ...]
    errors: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 2
        return 1 if any(gate.status == "fail" for gate in self.gates) else 0


def resolve_eval_bundle_root(
    *,
    public_eval_root: Path,
    split: EvalSplit,
    private_bundle: Path | None = None,
) -> Path:
    """Resolve a split without letting ordinary core runs inspect holdout files.

    A private bundle is deliberately opt-in and must be outside the public eval
    tree. Core tuning therefore cannot enumerate private case names, briefs,
    sources, expectations, or fixture contents as a side effect of startup.
    """

    public_root = public_eval_root.expanduser().resolve()
    if split == "core":
        if private_bundle is not None:
            raise ValueError("--private-bundle is only valid with --split holdout")
        return public_root
    if private_bundle is None:
        raise ValueError("--split holdout requires an explicit --private-bundle path")
    private_root = private_bundle.expanduser().resolve()
    if private_root == public_root or public_root in private_root.parents:
        raise ValueError("The holdout bundle must live outside the public benchmarks/eval tree")
    if not (private_root / "cases").is_dir():
        raise ValueError("The private holdout bundle is missing its cases directory")
    if not (private_root / "gates.toml").is_file():
        raise ValueError("The private holdout bundle is missing gates.toml")
    return private_root


def load_cases(eval_root: Path, case_ids: list[str] | None = None) -> list[EvalCase]:
    cases_root = eval_root / "cases"
    if not cases_root.exists():
        raise ValueError(f"Eval cases directory does not exist: {cases_root}")
    wanted = set(case_ids or [])
    directories = sorted(path for path in cases_root.iterdir() if path.is_dir())
    if wanted:
        unknown = wanted - {path.name for path in directories}
        if unknown:
            raise ValueError("Unknown eval case(s): " + ", ".join(sorted(unknown)))
        directories = [path for path in directories if path.name in wanted]
    cases: list[EvalCase] = []
    for directory in directories:
        case_path = directory / "case.toml"
        expectation_path = directory / "expectations.toml"
        if not case_path.exists():
            raise ValueError(f"{directory.name}: missing case.toml")
        try:
            data = tomllib.loads(case_path.read_text(encoding="utf-8"))
            brief = ResearchBrief.model_validate(data["brief"])
        except (OSError, KeyError, tomllib.TOMLDecodeError, ValueError) as exc:
            raise ValueError(f"{directory.name}: malformed case.toml: {exc}") from exc
        configured_sources = data.get("sources") or sorted(
            path.name for path in (directory / "sources").glob("*.md")
        )
        sources = tuple(
            (directory / "sources" / str(name)).resolve() for name in configured_sources
        )
        missing = [str(path) for path in sources if not path.is_file()]
        if missing:
            raise ValueError(f"{directory.name}: missing source file(s): {', '.join(missing)}")
        try:
            expectations = (
                tomllib.loads(expectation_path.read_text(encoding="utf-8"))
                if expectation_path.exists()
                else {}
            )
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"{directory.name}: malformed expectations.toml: {exc}") from exc
        cases.append(EvalCase(directory.name, directory, brief, sources, expectations))
    if not cases:
        raise ValueError("No evaluation cases were selected.")
    return cases


def load_gates(eval_root: Path) -> dict[str, float]:
    path = eval_root / "gates.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Invalid eval gates file: {exc}") from exc
    return {str(key): float(value) for key, value in raw.items()}


def dry_run(eval_root: Path, case_ids: list[str] | None = None) -> dict[str, Any]:
    cases = load_cases(eval_root, case_ids)
    gates = load_gates(eval_root)
    return {
        "cases": [
            {
                "case_id": case.case_id,
                "sources": [str(path) for path in case.sources],
                "sequence": [
                    "frozen brief",
                    "native markdown ingestion",
                    "source analysis",
                    "episode preparation",
                    "named plan approval",
                    "script pipeline",
                    "stop before audio",
                ],
            }
            for case in cases
        ],
        "gates": gates,
        "model_clients_constructed": 0,
    }


def run_eval(
    *,
    eval_root: Path,
    workspace_root: Path,
    case_ids: list[str] | None = None,
    settings: Settings | None = None,
) -> EvalReport:
    cases = load_cases(eval_root, case_ids)
    gate_config = load_gates(eval_root)
    metrics: list[CaseMetrics] = []
    errors: list[str] = []
    for case in cases:
        case_root = workspace_root / case.case_id
        if case_root.exists():
            shutil.rmtree(case_root)
        case_root.mkdir(parents=True, exist_ok=True)
        try:
            metrics.append(_run_case(case, case_root, settings=settings))
        except Exception as exc:
            errors.append(f"{case.case_id}: {type(exc).__name__}: {exc}")
    gates = evaluate_gates(metrics, gate_config)
    return EvalReport(
        generated_at=datetime.now(UTC).isoformat(),
        cases=tuple(metrics),
        gates=tuple(gates),
        errors=tuple(errors),
    )


def _build_services(settings: Settings, root: Path, project_id):
    """Mirror source_cli._model_service, episode_cli._service, and script_cli._service.

    The duplication is deliberate: evaluation must use the production composition
    without refactoring those independent composition roots in the same change.
    """

    return (
        build_source_service(settings, root),
        build_episode_service(settings, root, project_id),
        build_script_service(settings, root),
    )


def _run_case(case: EvalCase, root: Path, *, settings: Settings | None) -> CaseMetrics:
    started = time.perf_counter()
    base = settings or Settings()
    configured = base.model_copy(
        update={
            "workspace_root": root,
            "ingestion_artifact_root": root / "_ingestion",
            "observability_database_path": root / "_observability" / "ledger.sqlite3",
            "observability_artifact_root": root / "_observability" / "artifacts",
        }
    )
    tracing.install_tracer(tracer_from_settings(configured))
    workspace = WorkspaceStore(root)
    project = Project(raw_input=case.brief.normalized_topic, brief=case.brief)
    transition(project, ProjectState.BRIEF_READY)
    transition(project, ProjectState.SOURCES_COLLECTING)
    workspace.save_project(project)

    source_service, episode_service, script_service = _build_services(
        configured, root, project.project_id
    )
    for source_path in case.sources:
        source_id = uuid4()
        artifact_root = (
            configured.ensure_ingestion_artifact_root() / str(project.project_id) / str(source_id)
        )
        manifest = ingest_uploaded_source(
            source_path,
            source_id=source_id,
            filename=source_path.name,
            content_type="text/markdown",
            size_bytes=source_path.stat().st_size,
            settings=configured,
            artifact_root=artifact_root,
        )
        if not manifest.artifact_ref or not manifest.safe_for_claim_extraction:
            raise ValueError(
                f"{case.case_id}: source ingestion did not produce a safe artifact for "
                f"{source_path.name}: {manifest.issue_summary or manifest.status}"
            )
        source_service.analyze_source(
            project.project_id,
            artifact_root / manifest.artifact_ref,
            fast_model=configured.model_fast,
            strong_model=configured.model_strong,
            source_id=source_id,
            finalize_project=True,
        )

    coverage, _priorities, _budget, _graph, _plan, _packs = episode_service.prepare_episode(
        project.project_id,
        coverage_model=configured.model_strong,
        planning_model=configured.model_strong,
    )
    project = workspace.load_project(project.project_id)
    EpisodePlanApprovalStore(root).approve(project, approved_by="eval-harness")
    result = script_service.run(
        project.project_id,
        glossary_model=configured.model_strong,
        writer_model=configured.model_strong,
        verifier_model=configured.model_reviewer,
        reviser_model=configured.model_strong,
    )

    store = ScriptArtifactStore(root)
    checks = result.checks
    verification = result.verification
    outcome, _ = script_outcome(
        checks,
        verification,
        min_overall=(
            configured.script_quality_min_overall
            if configured.script_quality_gate_enabled
            else None
        ),
    )
    revision = store.load_revision_decision_optional(project.project_id)
    skipped = 0
    source_root = root / str(project.project_id) / "sources"
    for manifest_path in source_root.glob("*/manifest.json"):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        skipped += int(payload.get("skipped_block_count", 0))

    ledger = ObservabilityLedger(
        configured.resolved_observability_database_path,
        configured.resolved_observability_artifact_root,
    )
    usage = ObservabilityRollup(ledger).project_summary(project.project_id)
    cost_partial = usage.unpriced_succeeded_count > 0
    cost = None if cost_partial else usage.total_cost_micros
    per_minute = (
        round(cost / checks.estimated_minutes)
        if cost is not None and checks.estimated_minutes > 0
        else None
    )
    return CaseMetrics(
        case_id=case.case_id,
        project_id=str(project.project_id),
        checks_verdict=checks.verdict,
        verification_verdict=verification.verdict,
        unsupported_claim_ratio=verification.unsupported_claim_ratio,
        quality_overall=(verification.quality.overall if verification.quality else None),
        script_outcome=outcome,
        revision_accepted=revision.accepted if revision else None,
        revision_delta=revision.delta if revision else None,
        coverage_recommendation=coverage.recommendation,
        max_supported_minutes=coverage.max_supported_minutes,
        can_plan_episode=can_plan_episode_from_report(coverage, case.brief),
        estimated_minutes=checks.estimated_minutes,
        skipped_block_count=skipped,
        call_count=usage.call_count,
        failed_count=usage.failed_count,
        total_tokens=usage.total_tokens,
        wall_clock_seconds=round(time.perf_counter() - started, 3),
        cost_micros=cost,
        cost_is_partial=cost_partial,
        cost_micros_per_output_minute=per_minute,
        expectations=case.expectations,
    )


def can_plan_episode_from_report(coverage, brief: ResearchBrief) -> bool:
    from thesisound.services.coverage_auditor import can_plan_episode

    return can_plan_episode(
        recommendation=coverage.recommendation,
        max_supported_minutes=coverage.max_supported_minutes,
        target_duration_minutes=brief.target_duration_minutes,
    )


def evaluate_gates(
    cases: list[CaseMetrics],
    config: dict[str, float],
) -> list[GateEvaluation]:
    if not cases:
        return []
    values: dict[str, tuple[float | None, str]] = {
        "min_verified_case_rate": (
            sum(case.script_outcome == "verified" for case in cases) / len(cases),
            ">=",
        ),
        "max_unsupported_claim_ratio": (
            max(case.unsupported_claim_ratio for case in cases),
            "<=",
        ),
        "min_quality_overall": (
            (
                None
                if any(case.quality_overall is None for case in cases)
                else min(case.quality_overall for case in cases if case.quality_overall is not None)
            ),
            ">=",
        ),
        "max_failed_call_ratio": (
            sum(case.failed_count for case in cases)
            / max(1, sum(case.call_count for case in cases)),
            "<=",
        ),
        "max_cost_micros_per_output_minute": (
            max(
                (
                    case.cost_micros_per_output_minute
                    for case in cases
                    if case.cost_micros_per_output_minute is not None
                ),
                default=None,
            )
            if not any(case.cost_is_partial or case.cost_micros is None for case in cases)
            else None,
            "<=",
        ),
    }
    evaluations: list[GateEvaluation] = []
    for name, threshold in config.items():
        observed, comparison = values.get(name, (None, ">="))
        if observed is None:
            status: GateStatus = "skipped"
        elif comparison == ">=":
            status = "pass" if observed >= threshold else "fail"
        else:
            status = "pass" if observed <= threshold else "fail"
        evaluations.append(GateEvaluation(name, status, observed, threshold, comparison))
    return evaluations


def report_payload(report: EvalReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "cases": [asdict(case) for case in report.cases],
        "gates": [asdict(gate) for gate in report.gates],
        "errors": list(report.errors),
        "exit_code": report.exit_code,
    }


def report_markdown(report: EvalReport) -> str:
    lines = ["# Golden evaluation report", "", f"Generated: `{report.generated_at}`", ""]
    if report.errors:
        lines.extend(["## Case errors", ""] + [f"- {error}" for error in report.errors] + [""])
    lines.extend(
        [
            "## Release gates",
            "",
            "| Gate | Status | Observed | Threshold |",
            "|---|---|---:|---:|",
        ]
    )
    for gate in report.gates:
        observed = gate.observed if gate.observed is not None else "unknown"
        lines.append(
            f"| `{gate.name}` | **{gate.status}** | {observed} | "
            f"{gate.comparison} {gate.threshold} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Outcome | Checks | Verification | Quality | Unsupported | Calls | Cost |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for case in report.cases:
        quality = case.quality_overall if case.quality_overall is not None else "unknown"
        cost = case.cost_micros if case.cost_micros is not None else "unknown"
        lines.append(
            f"| `{case.case_id}` | {case.script_outcome} | {case.checks_verdict} | "
            f"{case.verification_verdict} | {quality} | "
            f"{case.unsupported_claim_ratio:.3f} | {case.call_count} | {cost} |"
        )
    lines.extend(
        [
            "",
            "Expectations are recorded in the JSON report for human review and are "
            "not asserted by this runner.",
            "",
        ]
    )
    return "\n".join(lines)
