from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import DocumentMap, EvidenceItem
from thesisound.ingestion import IngestionResult
from thesisound.source_analysis import (
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimLedger,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class SourceArtifactStore:
    """Atomic JSON/JSONL persistence for source-analysis artifacts."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def source_dir(self, project_id: UUID, source_id: UUID) -> Path:
        directory = self.workspace_root / str(project_id) / "sources" / str(source_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def list_claim_ready_source_ids(self, project_id: UUID) -> list[UUID]:
        root = self.workspace_root / str(project_id) / "sources"
        if not root.exists():
            return []
        source_ids: list[UUID] = []
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            manifest_path = directory / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = SourceAnalysisManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if manifest.status == "claims_ready":
                source_ids.append(manifest.source_id)
        return source_ids

    def save_ingestion(
        self,
        project_id: UUID,
        source_id: UUID,
        ingestion: IngestionResult,
    ) -> Path:
        directory = self.source_dir(project_id, source_id)
        self._write_json(directory / "ingestion-result.json", ingestion)
        if ingestion.parsed is not None:
            self._write_json(directory / "parsed-document.json", ingestion.parsed)
        return directory

    def save_blocks(
        self,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        report: BlockBuildReport,
    ) -> None:
        directory = self.source_dir(project_id, source_id)
        self._write_jsonl(directory / "document-blocks.jsonl", blocks)
        self._write_json(directory / "block-build-report.json", report)

    def load_blocks(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> list[SourceDocumentBlock]:
        path = self.source_dir(project_id, source_id) / "document-blocks.jsonl"
        return [
            SourceDocumentBlock.model_validate(item) for item in self._read_jsonl(path)
        ]

    def save_document_map(
        self,
        project_id: UUID,
        source_id: UUID,
        document_map: DocumentMap,
    ) -> None:
        self._write_json(
            self.source_dir(project_id, source_id) / "document-map.json",
            document_map,
        )

    def load_document_map(self, project_id: UUID, source_id: UUID) -> DocumentMap:
        return DocumentMap.model_validate_json(
            (self.source_dir(project_id, source_id) / "document-map.json").read_text(
                encoding="utf-8"
            )
        )

    def save_extraction_plan(
        self,
        project_id: UUID,
        source_id: UUID,
        plan: EvidenceExtractionPlan,
    ) -> None:
        self._write_json(
            self.source_dir(project_id, source_id) / "evidence-extraction-plan.json",
            plan,
        )

    def load_extraction_plan(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> EvidenceExtractionPlan:
        path = self.source_dir(project_id, source_id) / "evidence-extraction-plan.json"
        return EvidenceExtractionPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def save_block_extraction(
        self,
        project_id: UUID,
        source_id: UUID,
        record: BlockEvidenceExtraction,
    ) -> None:
        path = self.source_dir(project_id, source_id) / "evidence" / "extractions"
        self._write_json(path / f"{_safe_id(record.block_id)}.json", record)

    def block_extractions_dir(self, project_id: UUID, source_id: UUID) -> Path:
        return self.source_dir(project_id, source_id) / "evidence" / "extractions"

    def load_block_extractions(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> list[BlockEvidenceExtraction]:
        directory = self.block_extractions_dir(project_id, source_id)
        if not directory.exists():
            return []
        records: list[BlockEvidenceExtraction] = []
        for path in sorted(directory.glob("*.json")):
            records.append(
                BlockEvidenceExtraction.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        return records

    def prune_block_extractions(
        self,
        project_id: UUID,
        source_id: UUID,
        keep_block_ids: set[str],
    ) -> None:
        directory = self.block_extractions_dir(project_id, source_id)
        if not directory.exists():
            return
        keep_names = {_safe_id(block_id) + ".json" for block_id in keep_block_ids}
        for path in directory.glob("*.json"):
            if path.name not in keep_names:
                path.unlink(missing_ok=True)

    def save_evidence(
        self,
        project_id: UUID,
        source_id: UUID,
        records: list[BlockEvidenceExtraction],
    ) -> None:
        directory = self.source_dir(project_id, source_id)
        self._write_jsonl(directory / "evidence-extractions.jsonl", records)
        evidence = [claim for record in records for claim in record.extraction.claims]
        self._write_jsonl(directory / "evidence-items.jsonl", evidence)

    def load_evidence_items(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> list[EvidenceItem]:
        path = self.source_dir(project_id, source_id) / "evidence-items.jsonl"
        return [EvidenceItem.model_validate(item) for item in self._read_jsonl(path)]

    def load_extractions(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> list[BlockEvidenceExtraction]:
        path = self.source_dir(project_id, source_id) / "evidence-extractions.jsonl"
        return [
            BlockEvidenceExtraction.model_validate(item)
            for item in self._read_jsonl(path)
        ]

    def save_claim_ledger(
        self,
        project_id: UUID,
        source_id: UUID,
        ledger: ClaimLedger,
    ) -> None:
        self._write_json(
            self.source_dir(project_id, source_id) / "claim-ledger.json",
            ledger,
        )

    def load_claim_ledger(self, project_id: UUID, source_id: UUID) -> ClaimLedger:
        return ClaimLedger.model_validate_json(
            (self.source_dir(project_id, source_id) / "claim-ledger.json").read_text(
                encoding="utf-8"
            )
        )

    def save_manifest(self, manifest: SourceAnalysisManifest) -> None:
        self._write_json(
            self.source_dir(manifest.project_id, manifest.source_id) / "manifest.json",
            manifest,
        )

    def load_manifest(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> SourceAnalysisManifest:
        path = self.source_dir(project_id, source_id) / "manifest.json"
        return SourceAnalysisManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    @staticmethod
    def load_ingestion(path: Path) -> IngestionResult:
        resolved = path.expanduser().resolve()
        return IngestionResult.model_validate_json(
            resolved.read_text(encoding="utf-8")
        )

    @staticmethod
    def _write_json(
        path: Path,
        value: BaseModel | dict[str, Any] | list[Any],
    ) -> None:
        payload: Any = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _write_jsonl(path: Path, values: list[BaseModel]) -> None:
        lines = [
            json.dumps(
                value.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            for value in values
        ]
        _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_id(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_." else "-"
        for character in value
    )
