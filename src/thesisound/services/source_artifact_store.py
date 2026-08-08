from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import DocumentMap, EvidenceExtraction
from thesisound.ingestion import IngestionResult
from thesisound.source_analysis import (
    BlockBuildReport,
    ClaimLedger,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class SourceArtifactStore:
    """Atomic JSON/JSONL persistence for one-source analysis artifacts."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def source_dir(self, project_id: UUID, source_id: UUID) -> Path:
        directory = self.workspace_root / str(project_id) / "sources" / str(source_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

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

    def load_blocks(self, project_id: UUID, source_id: UUID) -> list[SourceDocumentBlock]:
        path = self.source_dir(project_id, source_id) / "document-blocks.jsonl"
        return [SourceDocumentBlock.model_validate(item) for item in self._read_jsonl(path)]

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

    def save_block_extraction(
        self,
        project_id: UUID,
        source_id: UUID,
        extraction: EvidenceExtraction,
        block_id: str,
    ) -> None:
        path = self.source_dir(project_id, source_id) / "evidence" / "extractions"
        self._write_json(path / f"{_safe_id(block_id)}.json", extraction)

    def save_evidence(
        self,
        project_id: UUID,
        source_id: UUID,
        extractions: list[EvidenceExtraction],
    ) -> None:
        directory = self.source_dir(project_id, source_id)
        self._write_jsonl(directory / "evidence-extractions.jsonl", extractions)
        evidence = [claim for extraction in extractions for claim in extraction.claims]
        self._write_jsonl(directory / "evidence-items.jsonl", evidence)

    def load_extractions(
        self,
        project_id: UUID,
        source_id: UUID,
    ) -> list[EvidenceExtraction]:
        path = self.source_dir(project_id, source_id) / "evidence-extractions.jsonl"
        return [EvidenceExtraction.model_validate(item) for item in self._read_jsonl(path)]

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

    def save_manifest(self, manifest: SourceAnalysisManifest) -> None:
        self._write_json(
            self.source_dir(manifest.project_id, manifest.source_id) / "manifest.json",
            manifest,
        )

    def load_manifest(self, project_id: UUID, source_id: UUID) -> SourceAnalysisManifest:
        path = self.source_dir(project_id, source_id) / "manifest.json"
        return SourceAnalysisManifest.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def load_ingestion(path: Path) -> IngestionResult:
        resolved = path.expanduser().resolve()
        return IngestionResult.model_validate_json(resolved.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _write_jsonl(path: Path, values: list[BaseModel]) -> None:
        lines = [
            json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for value in values
        ]
        _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
