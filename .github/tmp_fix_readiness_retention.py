from pathlib import Path

readiness_path = Path("src/thesisound/services/readiness.py")
text = readiness_path.read_text(encoding="utf-8")
old = '''            by_id = {block.block_id: block for block in blocks}\n            planned = [by_id[block_id] for block_id in plan.selected_block_ids if block_id in by_id]\n            kept_ids = {record.block_id for record in extracted}\n'''
new = '''            by_id = {block.block_id: block for block in blocks}\n            missing_block_ids = [\n                block_id for block_id in plan.selected_block_ids if block_id not in by_id\n            ]\n            if missing_block_ids:\n                missing = ", ".join(missing_block_ids[:4])\n                raise ValueError(f"Extraction plan references missing source block(s): {missing}")\n            planned = [by_id[block_id] for block_id in plan.selected_block_ids]\n            kept_ids = {record.block_id for record in extracted}\n'''
if text.count(old) != 1:
    raise SystemExit("retention anchor did not match exactly once")
readiness_path.write_text(text.replace(old, new), encoding="utf-8")

test_path = Path("tests/test_readiness.py")
tests = test_path.read_text(encoding="utf-8")
tests = tests.replace(
    '''    ProjectState,\n    ResearchBrief,\n''',
    '''    ProjectState,\n    ResearchBrief,\n    Locator,\n''',
)
tests = tests.replace(
    '''from thesisound.services.readiness import project_readiness\n''',
    '''from thesisound.services.readiness import _evidence_results, project_readiness\n''',
)
insert_after = '''from thesisound.services.script_artifact_store import ScriptArtifactStore\n'''
source_import = '''from thesisound.source_analysis import AnalysisProfile, EvidenceExtractionPlan, SourceDocumentBlock\n'''
if source_import not in tests:
    tests = tests.replace(insert_after, insert_after + source_import)
append = '''\n\ndef test_evidence_retention_unknown_when_plan_references_missing_block(tmp_path: Path) -> None:\n    source_id = uuid4()\n    source_dir = tmp_path / "source"\n    extraction_dir = source_dir / "evidence" / "extractions"\n    extraction_dir.mkdir(parents=True)\n    block = SourceDocumentBlock(\n        block_id="present",\n        source_id=source_id,\n        locator=Locator(page_start=1, page_end=1),\n        text="A valid source block with enough text.",\n        estimated_token_count=20,\n        source_block_keys=["block-1"],\n    )\n    (source_dir / "document-blocks.jsonl").write_text(\n        block.model_dump_json() + "\\n", encoding="utf-8"\n    )\n    plan = EvidenceExtractionPlan(\n        source_id=source_id,\n        profile=AnalysisProfile(\n            depth="brief",\n            target_duration_minutes=10,\n            block_coverage_target=0.5,\n            evidence_input_token_budget=100,\n            max_claims_per_block=3,\n            neighbor_context_blocks=0,\n            include_examples=False,\n            include_objections_and_responses=False,\n            second_pass_for_core_sections=False,\n        ),\n        selected_block_ids=["missing"],\n        deferred_block_ids=["present"],\n        selected_source_tokens=20,\n        total_source_tokens=40,\n        achieved_token_coverage=0.5,\n    )\n    (source_dir / "evidence-extraction-plan.json").write_text(\n        plan.model_dump_json(), encoding="utf-8"\n    )\n    statuses: dict[str, str] = {}\n\n    def capture(code: str, status: str, detail: str, evidence=None) -> None:\n        statuses[code] = status\n\n    _evidence_results([source_dir], capture)\n\n    assert statuses["evidence-validation"] == "unknown"\n    assert statuses["evidence-retention"] == "unknown"\n'''
if "test_evidence_retention_unknown_when_plan_references_missing_block" in tests:
    raise SystemExit("retention test already exists")
test_path.write_text(tests.rstrip() + append + "\n", encoding="utf-8")
