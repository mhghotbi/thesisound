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
from pathlib import Path
from typing import Any

from thesisound import tracing
from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.services import mineru_normalizer
from thesisound.services.mineru_normalizer import MineruOutputError, normalize_mineru_output
from thesisound.services.parser_identity import module_fingerprint

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

CommandRunner = Callable[
    [list[str], int, Mapping[str, str]],
    subprocess.CompletedProcess[str],
]


class MineruUnavailableError(RuntimeError):
    """Raised when the MinerU executable is not available."""


class MineruParseError(RuntimeError):
    """Raised when MinerU cannot produce a usable structured result."""


class MineruParser:
    name = "mineru"

    def __init__(
        self,
        *,
        command: str = "mineru",
        timeout_seconds: int = 1_800,
        backend: str | None = None,
        model_source: str | None = None,
        output_root: Path | None = None,
        runner: CommandRunner | None = None,
        version_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.backend = backend
        self.model_source = model_source
        self.output_root = output_root
        self._runner = runner
        self._version_resolver = version_resolver

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        if self._runner is not None or self._version_resolver is not None:
            return None
        version = self._version()
        if version == "unknown":
            return None
        impl = module_fingerprint(sys.modules[__name__], mineru_normalizer)
        if impl is None:
            return None
        return {
            "parser": "mineru",
            "mineru": version,
            "backend": self.backend or "",
            "model_source": self.model_source or "",
            "impl": impl,
        }

    def _output_fingerprint(self) -> str | None:
        """Name the (version, backend, model source) combination that would
        produce this raw output -- used only to place MinerU's own reuse
        directory, a narrower and more permissive concern than identity().

        Deliberately independent of identity(): normalize_mineru_output always
        re-runs against whatever JSON is on disk, so a changed normalizer does
        not make a previously completed CLI run stale, and an injected runner
        (used throughout this adapter's own tests) does not make a real,
        resolved CLI version any less real. identity() carries the stricter
        guard because it decides what the globally shared parsed-document
        cache may read; this only decides whether to skip a subprocess call.
        """

        version = self._version()
        if version == "unknown":
            return None
        payload = {
            "mineru": version,
            "backend": self.backend or "",
            "model_source": self.model_source or "",
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise MineruParseError(
                f"MinerU does not support this inspection: {inspection.extension or 'unknown'}"
            )

        fingerprint = self._output_fingerprint()
        if self.output_root is not None and fingerprint is not None:
            output_dir = (
                self.output_root.expanduser().resolve() / inspection.sha256[:16] / fingerprint
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            cleanup: Any = _NoopContext(output_dir)
        else:
            # No output_root, or an unresolvable CLI version: a run we cannot
            # name must not leave state another call could mistakenly reuse.
            cleanup = tempfile.TemporaryDirectory(prefix="thesisound-mineru-")

        with cleanup as temporary:
            output_dir = Path(temporary)
            marker = output_dir / ".mineru-complete"
            if not marker.exists():
                self._run(resolved, output_dir)
                marker.write_text("", encoding="utf-8")
            try:
                parsed = normalize_mineru_output(
                    output_dir,
                    source_path=resolved,
                    parser_version=self._version(),
                )
            except MineruOutputError as exc:
                raise MineruParseError(str(exc)) from exc

        if not parsed.blocks:
            raise MineruParseError("MinerU produced no usable content blocks.")
        return parsed

    def _run(self, source: Path, output_dir: Path) -> None:
        command = [self.command, "-p", str(source), "-o", str(output_dir)]
        if self.backend:
            command.extend(["-b", self.backend])
        environment = dict(os.environ)
        if self.model_source:
            environment["MINERU_MODEL_SOURCE"] = self.model_source

        # Every branch below either succeeds or raises -- unlike
        # document_ingestion.py's parser fallback loop, nothing here catches
        # and continues, so the span's own automatic exception handling
        # (status="error", error_type/error_message from the real exception)
        # is sufficient without a manual mark().
        with tracing.span(
            "ingestion.parse.mineru", component="ingestion", kind="subprocess"
        ) as span:
            span.set(timeout_seconds=self.timeout_seconds)
            runner = self._runner or _default_runner
            try:
                completed = runner(command, self.timeout_seconds, environment)
            except FileNotFoundError as exc:
                raise MineruUnavailableError(
                    "MinerU CLI was not found. Install with `uv sync --extra parsers` "
                    "and ensure 'mineru' is on PATH."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise MineruParseError(
                    f"MinerU exceeded the {self.timeout_seconds}-second timeout."
                ) from exc

            span.set(exit_code=completed.returncode)
            if completed.returncode != 0:
                message = _last_non_empty_line(completed.stderr) or _last_non_empty_line(
                    completed.stdout
                )
                detail = f": {message}" if message else ""
                span.set(stderr_tail=message or "")
                raise MineruParseError(f"MinerU exited with code {completed.returncode}{detail}")

    def _version(self) -> str:
        if self._version_resolver is not None:
            return self._version_resolver()
        executable = shutil.which(self.command)
        if executable is None:
            return "unknown"
        return _cached_mineru_version(executable)


class _NoopContext:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, *_: object) -> None:
        return None


def _default_runner(
    command: list[str],
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=dict(environment),
        check=False,
    )


def _last_non_empty_line(value: str | None) -> str | None:
    if not value:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:500] if lines else None


@cache
def _cached_mineru_version(executable: str) -> str:
    """Run `mineru --version` at most once per resolved executable per process.

    On Windows this is a console-script shim booting a fresh interpreter --
    realistically one to several seconds. build_web_parsers constructs a fresh
    MineruParser per upload, so caching on self would save nothing; this is
    keyed on the executable path instead, at module scope.
    """

    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    rendered = _last_non_empty_line(completed.stdout) or _last_non_empty_line(completed.stderr)
    return rendered or "unknown"
