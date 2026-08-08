from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from thesisound.ingestion import DocumentBenchmark, IngestionResult, ParseAttempt
from thesisound.ports import DocumentInspection

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")


class IngestionArtifactWriter:
    """Persist inspect, parse, quality, benchmark, and selection artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def document_dir(self, inspection: DocumentInspection) -> Path:
        safe_stem = _safe_name(inspection.path.stem)
        directory = self.root / f"{safe_stem}-{inspection.sha256[:16]}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write_inspection(self, inspection: DocumentInspection) -> Path:
        return self.write_json(
            self.document_dir(inspection) / "inspection.json",
            inspection,
        )

    def write_attempt(
        self,
        inspection: DocumentInspection,
        attempt: ParseAttempt,
    ) -> list[Path]:
        directory = self.document_dir(inspection) / "attempts" / _safe_name(attempt.parser_name)
        paths = [self.write_json(directory / "attempt.json", attempt)]
        if attempt.parsed is not None:
            paths.append(self.write_json(directory / "parsed-document.json", attempt.parsed))
        if attempt.quality is not None:
            paths.append(self.write_json(directory / "parse-quality.json", attempt.quality))
        return paths

    def write_result(self, result: IngestionResult) -> Path:
        return self.write_json(
            self.document_dir(result.inspection) / "ingestion-result.json",
            result,
        )

    def write_benchmark(self, benchmark: DocumentBenchmark) -> Path:
        safe_stem = _safe_name(benchmark.path.stem)
        directory = self.root / f"{safe_stem}-{benchmark.sha256[:16]}"
        return self.write_json(directory / "parser-benchmark.json", benchmark)

    def write_json(self, path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> Path:
        resolved = path.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, BaseModel):
            payload: Any = value.model_dump(mode="json")
        else:
            payload = value
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temporary = resolved.with_suffix(resolved.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(resolved)
        return resolved


def _safe_name(value: str) -> str:
    cleaned = _SAFE_NAME.sub("-", value).strip("-.")
    return cleaned or "document"
