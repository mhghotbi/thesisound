
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.services import ocr_contracts
from thesisound.services.ocr_contracts import OcrWorkerRequest
from thesisound.services.ocr_model_registry import (
    CORE_MODEL_NAMES,
    VLM_MODEL_NAME,
    ModelNotProvisionedError,
    OcrModelRegistry,
)
from thesisound.services.parser_identity import module_fingerprint

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
        render_dpi: int | None = None,
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
        # Explicit rather than left to OcrWorkerRequest's own default: it scales
        # the page rasteriser and is the single most output-affecting knob in the
        # OCR pipeline, so identity() must be able to see it.
        self.render_dpi = render_dpi or int(os.getenv("THESISOUND_OCR_RENDER_DPI", "180"))
        self._runner = runner

    @classmethod
    def from_environment(cls, *, output_root: Path | None = None) -> LocalOcrParser:
        return cls(output_root=output_root)

    def is_ready(self) -> bool:
        if not self.registry.core_ready():
            return False
        candidate = Path(self.python_command).expanduser()
        if (candidate.is_file() or shutil.which(self.python_command)) and (
            self.python_command != sys.executable
        ):
            return True
        return self.python_command == sys.executable and find_spec("paddleocr") is not None

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        if self._runner is not None:
            return None
        runtime = _ocr_runtime_fingerprint(self.python_command)
        if runtime is None:
            return None
        try:
            lock = self.registry.load_lock()
        except (OSError, ValueError, ModelNotProvisionedError):
            return None
        models = json.dumps(
            sorted(
                (
                    spec.name,
                    spec.repo_id,
                    spec.revision,
                    *sorted(anchor.sha256 for anchor in spec.anchors),
                )
                for spec in lock.models
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        impl = module_fingerprint(sys.modules[__name__], ocr_contracts)
        if impl is None:
            return None
        return {
            "parser": "local-ocr",
            "version": "1",
            "device": self.device,
            "enable_vlm": str(self.enable_vlm),
            "render_dpi": str(self.render_dpi),
            "models": models,
            "runtime": runtime,
            "impl": impl,
        }

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

        # A uuid-per-invocation subdirectory, not just <sha256[:16]>: two workers
        # OCR-ing the same file at once must not share one output/temp filename,
        # which on a cache-miss stampede is exactly when this collides.
        output_dir = self.output_root / inspection.sha256[:16] / uuid4().hex
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "parsed-document.json"
        request = OcrWorkerRequest(
            source_path=resolved,
            output_path=output_path,
            inspection=inspection,
            model_dirs=model_dirs,
            device=self.device,
            enable_vlm=self.enable_vlm,
            render_dpi=self.render_dpi,
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
        except (OSError, ValueError) as exc:
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


@cache
def _ocr_runtime_fingerprint(python_command: str) -> str | None:
    """Ask the OCR interpreter what it actually is, once per process.

    LocalOcrParser may run in a separate virtualenv (THESISOUND_OCR_PYTHON), so
    the calling process cannot see the paddleocr/PyMuPDF/Pillow versions that
    actually produced the text without asking that interpreter directly. Any
    failure -- missing interpreter, timeout, malformed output -- returns None,
    and the caller then declines to cache rather than share under a guess.
    """

    try:
        completed = subprocess.run(
            [python_command, "-m", "thesisound.ocr_runtime_probe"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_line(value: str | None) -> str | None:
    if not value:
        return None
    values = [line.strip() for line in value.splitlines() if line.strip()]
    return values[-1][:700] if values else None
