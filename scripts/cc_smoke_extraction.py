"""Live smoke: re-extract C-C skipped/flagged blocks and verify C-C fixes."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from thesisound import tracing
from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.observability import tracer_from_settings
from thesisound.prompt_loader import PromptLoader
from thesisound.services.evidence_extractor import EvidenceExtractorService, _full_profile
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import EvidenceExtractionPlan

PROJECT_ID = UUID("bfb5705c-74ab-5acf-b272-aa047a2545b3")
SOURCE_ID = UUID("336243a6-f029-582e-94c0-838d00fae635")
BLOCK_IDS = [
    "blk-336243a6-00054-0ea99ec2db54",
    "blk-336243a6-00055-f9f0a05390c9",
    "blk-336243a6-00056-e324fbf7401d",
    "blk-336243a6-00057-9d0d14d22955",
    "blk-336243a6-00042-f7aa919f145a",
    "blk-336243a6-00059-f73cea452505",
]


def main() -> None:
    tracing.install_tracer(tracer_from_settings())
    settings = Settings()
    root = settings.workspace_root.expanduser().resolve()
    store = SourceArtifactStore(root)
    blocks = store.load_blocks(PROJECT_ID, SOURCE_ID)
    document_map = store.load_document_map(PROJECT_ID, SOURCE_ID)
    block_by_id = {block.block_id: block for block in blocks}
    selected = [block_by_id[bid] for bid in BLOCK_IDS if bid in block_by_id]
    missing = [bid for bid in BLOCK_IDS if bid not in block_by_id]
    if missing:
        raise SystemExit(f"Missing blocks: {missing}")

    profile = _full_profile()
    plan = EvidenceExtractionPlan(
        source_id=SOURCE_ID,
        profile=profile,
        selected_block_ids=[block.block_id for block in selected],
        deferred_block_ids=[],
        selected_source_tokens=sum(block.estimated_token_count for block in selected),
        total_source_tokens=sum(block.estimated_token_count for block in blocks),
        achieved_token_coverage=1.0,
        target_source_tokens=1,
    )

    runner = ModelRunner(
        GeminiStructuredModel(api_key=settings.gemini_api_key),
        PromptLoader(),
        WorkspaceModelRunStore(root, keep_prompts=settings.keep_rendered_prompts),
        base_retry_delay_seconds=settings.model_retry_base_seconds,
    )
    extractor = EvidenceExtractorService(runner, max_workers=1, batch_size=1)
    started = datetime.now(UTC)

    results: list[dict[str, object]] = []

    def on_extraction(record) -> None:
        store.save_block_extraction(PROJECT_ID, SOURCE_ID, record)
        results.append(
            {
                "block_id": record.block_id,
                "status": record.status,
                "claims": len(record.extraction.claims),
                "more_claims_available": record.more_claims_available,
            }
        )
        print(
            f"{record.block_id} {record.status} claims={len(record.extraction.claims)} "
            f"more_claims={record.more_claims_available}",
            flush=True,
        )

    extractor.extract_source(
        project_id=PROJECT_ID,
        source_id=SOURCE_ID,
        blocks=blocks,
        document_map=document_map,
        model=settings.model_fast,
        plan=plan,
        on_extraction=on_extraction,
    )

    ledger_path = root / "_observability" / "ledger.sqlite3"
    con = sqlite3.connect(ledger_path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT is_synthetic, status, COUNT(*), SUM(total_tokens), SUM(cost_micros)
        FROM model_calls
        WHERE project_id = ?
          AND datetime(started_at) >= datetime(?)
          AND stage = 'evidence_extraction'
        GROUP BY is_synthetic, status
        """,
        (str(PROJECT_ID), started.isoformat()),
    )
    ledger_rows = cur.fetchall()
    con.close()

    report = {
        "started_at": started.isoformat(),
        "blocks": results,
        "ledger_by_synthetic_status": ledger_rows,
        "all_non_synthetic": all(row[0] == 0 for row in ledger_rows) if ledger_rows else None,
        "skipped_count": sum(1 for row in results if row["status"] == "skipped"),
        "more_claims_true": [row for row in results if row["more_claims_available"]],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
