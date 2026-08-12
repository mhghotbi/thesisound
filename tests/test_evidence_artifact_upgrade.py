from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from thesisound.cli_with_audio import app
from thesisound.domain import EvidenceItem, Locator, MustNotBeLostPoint, Project
from thesisound.pipeline import WorkspaceStore
from thesisound.services.evidence_artifact_migration import migrate_evidence_artifacts
from thesisound.services.evidence_artifact_upgrade import (
    CURRENT_EXTRACTION_SCHEMA_VERSION,
    EvidenceArtifactUpgradeError,
    resolve_block_locator,
    upgrade_block_extraction_payload,
)
from thesisound.services.readiness import GateResult, _evidence_results
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockBuildReport,
    BlockEvidenceExtraction,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "evidence_artifacts"
_SOURCE_ID = UUID("4c598a0d-6454-4a87-9f8a-735364c44118")
_BLOCK_LOCATOR = Locator(page_start=12, page_end=12, chapter="Intro", section="Intro")
_BLOCK_TEXT = "A valid source block with enough text for retention checks."


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _claim(*, source_id: UUID, block_id: str) -> dict:
    return EvidenceItem(
        evidence_id=f"ev-{block_id}",
        source_id=source_id,
        block_id=block_id,
        claim="A grounded claim from the fixture block.",
        claim_type="author_position",
        supporting_excerpt=_BLOCK_TEXT,
        locator=_BLOCK_LOCATOR,
        support_kind="direct",
        confidence=1.0,
    ).model_dump(mode="json")


def test_upgrade_lifts_string_must_not_be_lost() -> None:
    payload = _load_fixture("must_not_be_lost_string.json")
    upgraded = upgrade_block_extraction_payload(payload, block_locator=_BLOCK_LOCATOR)
    record = BlockEvidenceExtraction.model_validate(upgraded)

    assert len(record.extraction.must_not_be_lost) == 1
    point = record.extraction.must_not_be_lost[0]
    assert isinstance(point, MustNotBeLostPoint)
    assert point.text == "The book does not offer a utopian blueprint."
    assert point.source_id == _SOURCE_ID
    assert point.block_id == "blk-fixture-must-not-be-lost"
    assert point.locator == _BLOCK_LOCATOR
    assert record.schema_version == CURRENT_EXTRACTION_SCHEMA_VERSION


def test_upgrade_injects_ids_into_definitions() -> None:
    payload = _load_fixture("definitions_missing_ids.json")
    stored_locator = payload["extraction"]["definitions"][0]["locator"]
    upgraded = upgrade_block_extraction_payload(payload, block_locator=_BLOCK_LOCATOR)
    record = BlockEvidenceExtraction.model_validate(upgraded)

    definition = record.extraction.definitions[0]
    assert definition.source_id == _SOURCE_ID
    assert definition.block_id == "blk-fixture-definitions"
    assert definition.locator.model_dump(mode="json") == stored_locator

    distinction = record.extraction.distinctions[0]
    assert distinction.source_id == _SOURCE_ID
    assert distinction.block_id == "blk-fixture-definitions"


def test_upgrade_is_idempotent() -> None:
    payload = _load_fixture("definitions_missing_ids.json")
    once = upgrade_block_extraction_payload(payload, block_locator=_BLOCK_LOCATOR)
    twice = upgrade_block_extraction_payload(once, block_locator=_BLOCK_LOCATOR)
    assert twice == once


def test_upgrade_refuses_unknown_block() -> None:
    payload = _load_fixture("must_not_be_lost_string.json")
    with pytest.raises(EvidenceArtifactUpgradeError, match="no locator"):
        resolve_block_locator(payload, {})


def test_upgrade_preserves_present_values() -> None:
    other_source = uuid4()
    payload = _load_fixture("definitions_missing_ids.json")
    payload["extraction"]["definitions"][0]["source_id"] = str(other_source)
    payload["extraction"]["definitions"][0]["block_id"] = "already-set"
    upgraded = upgrade_block_extraction_payload(payload, block_locator=_BLOCK_LOCATOR)
    item = upgraded["extraction"]["definitions"][0]
    assert item["source_id"] == str(other_source)
    assert item["block_id"] == "already-set"


def test_upgrade_round_trips_model_dump() -> None:
    payload = _load_fixture("definitions_missing_ids.json")
    upgraded = upgrade_block_extraction_payload(payload, block_locator=_BLOCK_LOCATOR)
    record = BlockEvidenceExtraction.model_validate(upgraded)
    again = BlockEvidenceExtraction.model_validate(record.model_dump(mode="json"))
    assert again == record


def _write_source_with_extraction(
    root: Path,
    *,
    source_id: UUID,
    block_id: str,
    payload: dict,
    corrupt: bool = False,
) -> Path:
    source_dir = root / str(source_id)
    extraction_dir = source_dir / "evidence" / "extractions"
    extraction_dir.mkdir(parents=True)
    block = SourceDocumentBlock(
        block_id=block_id,
        source_id=source_id,
        locator=_BLOCK_LOCATOR,
        text=_BLOCK_TEXT,
        estimated_token_count=40,
        source_block_keys=["block-1"],
    )
    (source_dir / "document-blocks.jsonl").write_text(
        block.model_dump_json() + "\n", encoding="utf-8"
    )
    plan = EvidenceExtractionPlan(
        source_id=source_id,
        profile=AnalysisProfile(
            depth="brief",
            target_duration_minutes=10,
            block_coverage_target=0.5,
            evidence_input_token_budget=100,
            max_claims_per_block=3,
            neighbor_context_blocks=0,
            include_examples=False,
            include_objections_and_responses=False,
            second_pass_for_core_sections=False,
        ),
        selected_block_ids=[block_id],
        deferred_block_ids=[],
        selected_source_tokens=40,
        total_source_tokens=40,
        achieved_token_coverage=1.0,
    )
    (source_dir / "evidence-extraction-plan.json").write_text(
        plan.model_dump_json(), encoding="utf-8"
    )
    path = extraction_dir / f"{block_id}.json"
    if corrupt:
        path.write_text("{not-json", encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return source_dir


def _capture_bucket(bucket: dict[str, GateResult]):
    def capture(
        code: str,
        status: str,
        detail: str,
        evidence=None,
        reason=None,
    ) -> None:
        bucket[code] = GateResult(
            code=code,
            label=code,
            actor="system",
            status=status,  # type: ignore[arg-type]
            detail=detail,
            evidence=str(evidence) if evidence is not None else None,
            reason=reason,
        )

    return capture


def test_readiness_isolates_one_corrupt_artifact(tmp_path: Path) -> None:
    good_source = uuid4()
    bad_source = uuid4()
    good_payload = _load_fixture("must_not_be_lost_string.json")
    good_payload["source_id"] = str(good_source)
    good_payload["block_id"] = "good-block"
    good_payload["extraction"]["claims"] = [
        _claim(source_id=good_source, block_id="good-block")
    ]

    good_dir = _write_source_with_extraction(
        tmp_path,
        source_id=good_source,
        block_id="good-block",
        payload=good_payload,
    )
    bad_dir = _write_source_with_extraction(
        tmp_path,
        source_id=bad_source,
        block_id="bad-block",
        payload={},
        corrupt=True,
    )

    captured: dict[str, GateResult] = {}
    _evidence_results([good_dir, bad_dir], _capture_bucket(captured))

    assert captured["evidence-validation"].status == "pass"
    assert "bad-block.json" in captured["evidence-validation"].detail
    assert captured["evidence-retention"].status == "unknown"
    assert captured["evidence-retention"].reason in {"schema", "io"}


def test_readiness_retention_unknown_when_artifact_skipped(tmp_path: Path) -> None:
    source_id = uuid4()
    payload = _load_fixture("must_not_be_lost_string.json")
    payload["source_id"] = str(source_id)
    payload["block_id"] = "kept-block"
    payload["extraction"]["claims"] = [
        _claim(source_id=source_id, block_id="kept-block")
    ]
    source_dir = _write_source_with_extraction(
        tmp_path,
        source_id=source_id,
        block_id="kept-block",
        payload=payload,
    )
    (source_dir / "evidence" / "extractions" / "other-block.json").write_text(
        "{broken", encoding="utf-8"
    )

    captured: dict[str, GateResult] = {}
    _evidence_results([source_dir], _capture_bucket(captured))

    assert captured["evidence-validation"].status == "pass"
    assert captured["evidence-retention"].status == "unknown"
    assert "other-block.json" in captured["evidence-retention"].detail


def test_gate_result_reason_schema_vs_contract(tmp_path: Path) -> None:
    schema_source = uuid4()
    contract_source = uuid4()

    schema_dir = _write_source_with_extraction(
        tmp_path / "schema",
        source_id=schema_source,
        block_id="schema-block",
        payload={},
        corrupt=True,
    )

    contract_payload = _load_fixture("must_not_be_lost_string.json")
    contract_payload["source_id"] = str(contract_source)
    contract_payload["block_id"] = "present"
    contract_payload["extraction"]["claims"] = [
        _claim(source_id=contract_source, block_id="present")
    ]
    contract_dir = _write_source_with_extraction(
        tmp_path / "contract",
        source_id=contract_source,
        block_id="present",
        payload=contract_payload,
    )
    plan = EvidenceExtractionPlan.model_validate_json(
        (contract_dir / "evidence-extraction-plan.json").read_text(encoding="utf-8")
    )
    plan = plan.model_copy(update={"selected_block_ids": ["missing"]})
    (contract_dir / "evidence-extraction-plan.json").write_text(
        plan.model_dump_json(), encoding="utf-8"
    )

    schema_capture: dict[str, GateResult] = {}
    contract_capture: dict[str, GateResult] = {}
    _evidence_results([schema_dir], _capture_bucket(schema_capture))
    _evidence_results([contract_dir], _capture_bucket(contract_capture))

    assert schema_capture["evidence-validation"].status == "unknown"
    assert schema_capture["evidence-validation"].reason == "schema"
    assert contract_capture["evidence-retention"].status == "unknown"
    assert contract_capture["evidence-retention"].reason == "contract"
    assert (
        schema_capture["evidence-validation"].reason
        != contract_capture["evidence-retention"].reason
    )


def test_migrate_reports_unfixable_when_blocks_missing_and_jsonl_unreadable(
    tmp_path: Path,
) -> None:
    """Missing blocks + unreadable jsonl must not crash; count as unfixable."""

    root = tmp_path / "workspaces"
    project = Project(raw_input="topic")
    WorkspaceStore(root).save_project(project)
    source_id = uuid4()
    store = SourceArtifactStore(root)
    source_dir = store.source_dir(project.project_id, source_id)
    source_dir.mkdir(parents=True, exist_ok=True)
    # No document-blocks.jsonl → load_blocks fails. Corrupt jsonl so the
    # fallback count path cannot read_text either.
    (source_dir / "evidence-extractions.jsonl").write_bytes(b"\xff\xfe not utf-8\n")

    report = migrate_evidence_artifacts(
        workspace_root=root, project_id=project.project_id, dry_run=True
    )
    assert len(report.sources) == 1
    stats = report.sources[0]
    assert stats.as_is == 0
    assert stats.upgraded == 0
    assert stats.unfixable >= 1


def test_migrate_reports_unfixable_when_jsonl_unreadable_with_blocks(
    tmp_path: Path,
) -> None:
    """Blocks load OK but corrupt/unreadable jsonl must not crash migration."""

    root = tmp_path / "workspaces"
    project = Project(raw_input="topic")
    WorkspaceStore(root).save_project(project)
    source_id = uuid4()
    store = SourceArtifactStore(root)
    block = SourceDocumentBlock(
        block_id="blk-1",
        source_id=source_id,
        locator=_BLOCK_LOCATOR,
        text="Block text for migration fixtures.",
        estimated_token_count=20,
        source_block_keys=["k1"],
    )
    store.save_blocks(
        project.project_id,
        source_id,
        [block],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=1,
            output_block_count=1,
        ),
    )
    # Only aggregate jsonl (no per-block JSON); encoding is invalid UTF-8.
    jsonl_path = store.source_dir(project.project_id, source_id) / (
        "evidence-extractions.jsonl"
    )
    jsonl_path.write_bytes(b"\xff\xfe not utf-8\n")

    report = migrate_evidence_artifacts(
        workspace_root=root, project_id=project.project_id, dry_run=True
    )
    assert len(report.sources) == 1
    stats = report.sources[0]
    assert stats.as_is == 0
    assert stats.upgraded == 0
    assert stats.unfixable == 1


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = Project(raw_input="topic")
    WorkspaceStore(root).save_project(project)
    source_id = uuid4()
    store = SourceArtifactStore(root)
    block = SourceDocumentBlock(
        block_id="blk-fixture-must-not-be-lost",
        source_id=source_id,
        locator=_BLOCK_LOCATOR,
        text="Block text for migration fixtures.",
        estimated_token_count=20,
        source_block_keys=["k1"],
    )
    store.save_blocks(
        project.project_id,
        source_id,
        [block],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=1,
            output_block_count=1,
        ),
    )
    payload = _load_fixture("must_not_be_lost_string.json")
    payload["source_id"] = str(source_id)
    path = store.block_extractions_dir(project.project_id, source_id)
    path.mkdir(parents=True)
    (path / "blk-fixture-must-not-be-lost.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    first = migrate_evidence_artifacts(
        workspace_root=root, project_id=project.project_id, dry_run=False
    )
    assert first.upgraded == 1
    assert first.unfixable == 0

    second = migrate_evidence_artifacts(
        workspace_root=root, project_id=project.project_id, dry_run=False
    )
    assert second.upgraded == 0
    assert second.as_is == 1
    assert second.unfixable == 0

    loaded = store.load_block_extractions(
        project.project_id,
        source_id,
        block_locators=store.load_block_locators(project.project_id, source_id),
    )
    assert loaded[0].schema_version == CURRENT_EXTRACTION_SCHEMA_VERSION
    assert loaded[0].extraction.must_not_be_lost[0].text


def test_migrate_cli_dry_run_default(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = Project(raw_input="topic")
    WorkspaceStore(root).save_project(project)
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "evidence-artifacts",
            "--project",
            str(project.project_id),
            "--workspace-root",
            str(root),
        ],
    )
    assert result.exit_code == 0
    assert "dry-run" in result.stdout.lower()
