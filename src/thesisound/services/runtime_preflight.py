from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Literal
from uuid import uuid4

from thesisound import tracing
from thesisound.config import Settings
from thesisound.model_routing import load_model_router
from thesisound.modeling import ModelConfigurationError

PreflightScope = Literal["model", "audio", "full"]
PreflightStatus = Literal["pass", "warning", "fail"]


@dataclass(frozen=True, slots=True)
class RuntimeCheck:
    code: str
    label: str
    status: PreflightStatus
    detail: str

    @property
    def blocking(self) -> bool:
        return self.status == "fail"


class RuntimePreflight:
    """Check local prerequisites before a run can spend provider time or money."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, scope: PreflightScope = "full") -> list[RuntimeCheck]:
        checks = [
            self._writable_directory(
                "workspace",
                "Project workspace",
                self.settings.workspace_root,
            ),
            self._writable_directory(
                "ingestion-artifacts",
                "Ingestion artifact path",
                self.settings.ingestion_artifact_root,
            ),
            self._gemini_key(),
            self._model_routing(),
            self._okian_provider(),
            self._python_module(
                "google-genai",
                "Gemini model SDK",
                "google.genai",
                "Install with `uv sync --extra gemini`.",
            ),
            self._grounding_tool(
                "gemini-google-search",
                "Gemini Google Search",
                self.settings.gemini_google_search_enabled,
                "Enabled for brief, discovery, and terminology.",
            ),
            self._grounding_tool(
                "gemini-url-context",
                "Gemini URL Context",
                self.settings.gemini_url_context_enabled,
                "Enabled for explicit public URLs in the prompt.",
            ),
            RuntimeCheck(
                code="parser-epub",
                label="EPUB",
                status="pass",
                detail="Parser داخلی EPUB 2/3 با خواندن manifest و spine در دسترس است.",
            ),
        ]
        if scope in {"audio", "full"}:
            checks.append(self._ffmpeg())
        if scope == "full":
            checks.extend(self._parser_checks())
        failed = [check.code for check in checks if check.blocking]
        if failed:
            # A span for every call would be noise on the (overwhelming) happy
            # path -- this runs on every gated request. Only the interesting
            # case, a block that will redirect the user to /system-check, is
            # worth a record.
            tracing.event(
                "preflight.blocked",
                component="preflight",
                level="warn",
                scope=scope,
                failed_checks=failed,
            )
        return checks

    def require(self, scope: PreflightScope) -> None:
        failures = [check for check in self.run(scope) if check.blocking]
        if not failures:
            return
        detail = "; ".join(f"{check.label}: {check.detail}" for check in failures)
        raise RuntimeError(
            "Live-run prerequisites are incomplete. "
            f"{detail} See `/system-check` or `uv run thesisound doctor` for details."
        )

    def ready(self, scope: PreflightScope) -> bool:
        return not any(check.blocking for check in self.run(scope))

    def _gemini_key(self) -> RuntimeCheck:
        key_count = len(self.settings.gemini_api_keys)
        if key_count:
            return RuntimeCheck(
                code="gemini-api-key",
                label="Gemini API key",
                status="pass",
                detail=f"{key_count} key(s) configured in the pool.",
            )
        return RuntimeCheck(
            code="gemini-api-key",
            label="Gemini API key",
            status="fail",
            detail=(
                "`GEMINI_API_KEYS` or `GEMINI_API_KEY` is not set in the environment "
                "or `.env` file."
            ),
        )

    def _model_routing(self) -> RuntimeCheck:
        try:
            router = load_model_router(self.settings)
        except ModelConfigurationError as exc:
            return RuntimeCheck(
                code="model-routing",
                label="Model routing",
                status="fail",
                detail=str(exc),
            )
        return RuntimeCheck(
            code="model-routing",
            label="Model routing",
            status="pass",
            detail=(
                f"Loaded `{self.settings.model_routing_file}`; "
                f"Okian active: {router.uses_provider('okian')}."
            ),
        )

    def _okian_provider(self) -> RuntimeCheck:
        try:
            active = load_model_router(self.settings).uses_provider("okian")
        except ModelConfigurationError:
            active = False
        base_url = (self.settings.okian_base_url or "").strip()
        api_key = (self.settings.okian_api_key or "").strip()
        if active and (not base_url or not api_key):
            return RuntimeCheck(
                code="okian-provider",
                label="Okian provider",
                status="fail",
                detail=(
                    "An active route uses Okian, but OKIAN_BASE_URL and "
                    "OKIAN_API_KEY are not both configured."
                ),
            )
        if base_url and api_key:
            return RuntimeCheck(
                code="okian-provider",
                label="Okian provider",
                status="pass",
                detail=(
                    "Credentials configured; provider is active in routing."
                    if active
                    else "Credentials configured; no stage is routed to Okian."
                ),
            )
        if base_url or api_key:
            return RuntimeCheck(
                code="okian-provider",
                label="Okian provider",
                status="warning",
                detail=(
                    "Only one of OKIAN_BASE_URL or OKIAN_API_KEY is configured; "
                    "no active Okian route will run."
                ),
            )
        return RuntimeCheck(
            code="okian-provider",
            label="Okian provider",
            status="pass",
            detail="Not configured and not used by any route.",
        )

    @staticmethod
    def _grounding_tool(
        code: str,
        label: str,
        enabled: bool,
        enabled_detail: str,
    ) -> RuntimeCheck:
        if enabled:
            return RuntimeCheck(
                code=code,
                label=label,
                status="pass",
                detail=enabled_detail,
            )
        return RuntimeCheck(
            code=code,
            label=label,
            status="warning",
            detail="Disabled in settings.",
        )

    def _ffmpeg(self) -> RuntimeCheck:
        command = shutil.which(self.settings.ffmpeg_command)
        if command:
            return RuntimeCheck(
                code="ffmpeg",
                label="FFmpeg",
                status="pass",
                detail=f"Found at `{command}`.",
            )
        return RuntimeCheck(
            code="ffmpeg",
            label="FFmpeg",
            status="fail",
            detail=(
                f"`{self.settings.ffmpeg_command}` is not on PATH; "
                "final assembly and loudness normalization require it."
            ),
        )

    def _parser_checks(self) -> list[RuntimeCheck]:
        checks = [
            RuntimeCheck(
                code="parser-native",
                label="Base parser",
                status="pass",
                detail="Native parser is available for text PDFs, TXT, Markdown, and DOCX.",
            )
        ]
        if _module_available("docling"):
            checks.append(
                RuntimeCheck(
                    code="parser-docling",
                    label="Docling",
                    status="pass",
                    detail="Installed in the Python environment.",
                )
            )
        else:
            checks.append(
                RuntimeCheck(
                    code="parser-docling",
                    label="Docling",
                    status="warning",
                    detail="Not installed; add `--extra parsers` for complex PDFs.",
                )
            )

        mineru = _command_path(self.settings.mineru_command)
        if mineru:
            checks.append(
                RuntimeCheck(
                    code="parser-mineru",
                    label="MinerU",
                    status="pass",
                    detail=f"Found at `{mineru}`.",
                )
            )
        else:
            checks.append(
                RuntimeCheck(
                    code="parser-mineru",
                    label="MinerU",
                    status="warning",
                    detail="Not on PATH; add `--extra parsers` for scanned/complex PDF fallback.",
                )
            )
        return checks

    def _python_module(
        self,
        code: str,
        label: str,
        module: str,
        missing_detail: str,
    ) -> RuntimeCheck:
        if _module_available(module):
            return RuntimeCheck(code=code, label=label, status="pass", detail="Installed.")
        return RuntimeCheck(
            code=code,
            label=label,
            status="fail",
            detail=missing_detail,
        )

    def _writable_directory(self, code: str, label: str, path: Path) -> RuntimeCheck:
        resolved = path.expanduser().resolve()
        probe = resolved / f".thesisound-preflight-{uuid4().hex}"
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return RuntimeCheck(
                code=code,
                label=label,
                status="fail",
                detail=f"Not writable: {exc}",
            )
        return RuntimeCheck(
            code=code,
            label=label,
            status="pass",
            detail=f"`{resolved}` is writable.",
        )


def _module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _command_path(command: str) -> str | None:
    candidate = Path(command).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate.resolve()) if candidate.is_file() else None
    return shutil.which(command)
