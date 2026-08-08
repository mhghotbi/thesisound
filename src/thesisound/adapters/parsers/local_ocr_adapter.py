
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from importlib.util import find_spec
from pathlib import Path

from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.services.ocr_contracts import OcrWorkerRequest
from thesisound.services.ocr_model_registry import (
    CORE_MODEL_NAMES,
    VLM_MODEL_NAME,
    ModelNotProvisionedError,
    OcrModelRegistry,
)

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}
Runner = Callable[[list[str], int, Mapping[str, str]], subprocess.CompletedProcess[str]]


class LocalOcrUnavailableError(RuntimeError):
    """Raised when the isolated local OCR runtime is not ready."""


class LocalOcrParseError(RuntimeError):
    """Raised when the short-lived OCR worker cannot return a parsed document."""


class LocalOcrParser:
    name = "local-ocr"

    def __init__(
        self,
        *,
        registry: OcrModelRegistry | None = None,
        output_root: Path | None = None,
        timeout_seconds: int | None = None,
        python_command: str | None = None,
        device: str | None = None,
        enable_vlm: bool | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.registry = registry or OcrModelRegistry.from_environment()
        self.output_root = (output_root or Path(os.getenv(
            "THESISOUND_OCR_ARTIFACT_ROOT", "artifacts/ingestion/raw/local-ocr"
        ))).expanduser().resolve()
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("THESISOUND_OCR_TIMEOUT_SECONDS", "1800")
        )
        self.python_command = python_command or os.getenv(
            "THESISOUND_OCR_PYTHON", sys.executable
        )
        self.device = device or os.getenv("THESISOUND_OCR_DEVICE", "cpu")
        configured_vlm = os.getenv("THESISOUND_OCR_ENABLE_VLM", "false").lower() in {
            "1", "true", "yes"
        }
        self.enable_vlm = configured_vlm if enable_vlm is None else enable_vlm
        self._runner = runner

    @classmethod
    def from_environment(cls, *, output_root: Path | None = None) -> LocalOcrParser:
        return cls(output_root=output_root)

    def is_ready(self) -> bool:
        if not self.registry.core_ready():
            return False
        candidate = Path(self.python_command).expanduser()
        if candidate.is_file() or shutil.which(self.python_command):
            if self.python_command != sys.executable:
                return True
        return self.python_command == sys.executable and find_spec("paddleocr") is not None

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise LocalOcrParseError(
                f"Local OCR does not support: {inspection.extension or 'unknown'}"
            )
        try:
            model_dirs = self.registry.require(list(CORE_MODEL_NAMES))
            if self.enable_vlm:
                model_dirs.update(self.registry.require([VLM_MODEL_NAME]))
        except ModelNotProvisionedError as exc:
            raise LocalOcrUnavailableError(str(exc)) from exc

        output_dir = self.output_root / inspection.sha256[:16]
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "parsed-document.json"
        request = OcrWorkerRequest(
            source_path=resolved,
            output_path=output_path,
            inspection=inspection,
            model_dirs=model_dirs,
            device=self.device,
            enable_vlm=self.enable_vlm,
        )
        with tempfile.TemporaryDirectory(prefix="thesisound-ocr-request-") as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
            command = [
                self.python_command,
                "-m",
                "thesisound.ocr_worker",
                "--request",
                str(request_path),
            ]
            runner = self._runner or _default_runner
            try:
                completed = runner(
                    command,
                    self.timeout_seconds,
                    self.registry.runtime_environment(),
                )
            except FileNotFoundError as exc:
                raise LocalOcrUnavailableError(
                    f"OCR Python executable not found: {self.python_command}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise LocalOcrParseError(
                    f"Local OCR exceeded the {self.timeout_seconds}-second timeout."
                ) from exc
        if completed.returncode != 0:
            detail = _last_line(completed.stderr) or _last_line(completed.stdout)
            raise LocalOcrParseError(
                f"Local OCR worker exited with code {completed.returncode}"
                + (f": {detail}" if detail else "")
            )
        try:
            parsed = ParsedDocument.model_validate_json(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueEError) as exc:
            raise LocalOcrParseError("Local OCR worker returned no valid parsed document.") from exc
        if not parsed.blocks:
            raise LocalOcrParseError("Local OCR produced no usable content blocks.")
        return parsed


def _default_runner(
    command: list[str], timeout_seconds: int, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=dict(environment),
        check=False,
    )


def _last_line(value: str | None) -> str | None:
    if not value:
        return None
    values = [line.strip() for line in value.splitlines() if line.strip()]
    return values[-1][:700] if values else None
