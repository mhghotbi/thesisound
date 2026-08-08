
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from thesisound.ports import DocumentInspection


class OcrWorkerRequest(BaseModel):
    source_path: Path
    output_path: Path
    inspection: DocumentInspection
    model_dirs: dict[str, Path]
    device: str = "cpu"
    enable_vlm: bool = False
    render_dpi: int = Field(default=180, ge=96, le=300)
