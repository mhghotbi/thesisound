from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Literal
from uuid import uuid4

from thesisound.config import Settings

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
                "مسیر پروژه‌ها",
                self.settings.workspace_root,
            ),
            self._writable_directory(
                "ingestion-artifacts",
                "مسیر artifactهای ingestion",
                self.settings.ingestion_artifact_root,
            ),
            self._gemini_key(),
            self._python_module(
                "google-genai",
                "SDK مدل Gemini",
                "google.genai",
                "با `uv sync --extra gemini` نصب شود.",
            ),
            self._grounding_tool(
                "gemini-google-search",
                "Gemini Google Search",
                self.settings.gemini_google_search_enabled,
                "برای brief، discovery و اصطلاح‌شناسی فعال است.",
            ),
            self._grounding_tool(
                "gemini-url-context",
                "Gemini URL Context",
                self.settings.gemini_url_context_enabled,
                "برای URL عمومیِ صریح در prompt فعال است.",
            ),
        ]
        if scope in {"audio", "full"}:
            checks.append(self._ffmpeg())
        if scope == "full":
            checks.extend(self._parser_checks())
        return checks

    def require(self, scope: PreflightScope) -> None:
        failures = [check for check in self.run(scope) if check.blocking]
        if not failures:
            return
        detail = "؛ ".join(f"{check.label}: {check.detail}" for check in failures)
        raise RuntimeError(
            "پیش‌نیازهای اجرای واقعی کامل نیست. "
            f"{detail} برای جزئیات `/system-check` یا `uv run thesisound doctor` را ببینید."
        )

    def ready(self, scope: PreflightScope) -> bool:
        return not any(check.blocking for check in self.run(scope))

    def _gemini_key(self) -> RuntimeCheck:
        key_count = len(self.settings.gemini_api_keys)
        if key_count:
            return RuntimeCheck(
                code="gemini-api-key",
                label="کلید Gemini",
                status="pass",
                detail=f"{key_count} کلید در pool تنظیم شده است.",
            )
        return RuntimeCheck(
            code="gemini-api-key",
            label="کلید Gemini",
            status="fail",
            detail=(
                "`GEMINI_API_KEYS` یا `GEMINI_API_KEY` در محیط یا فایل `.env` "
                "تنظیم نشده است."
            ),
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
            detail="در تنظیمات غیرفعال شده است.",
        )

    def _ffmpeg(self) -> RuntimeCheck:
        command = shutil.which(self.settings.ffmpeg_command)
        if command:
            return RuntimeCheck(
                code="ffmpeg",
                label="FFmpeg",
                status="pass",
                detail=f"در `{command}` پیدا شد.",
            )
        return RuntimeCheck(
            code="ffmpeg",
            label="FFmpeg",
            status="fail",
            detail=(
                f"فرمان `{self.settings.ffmpeg_command}` روی PATH نیست؛ "
                "بدون آن assembly و loudness normalization نهایی انجام نمی‌شود."
            ),
        )

    def _parser_checks(self) -> list[RuntimeCheck]:
        checks = [
            RuntimeCheck(
                code="parser-native",
                label="Parser پایه",
                status="pass",
                detail="Native parser برای PDF متنی، TXT، Markdown و DOCX در دسترس است.",
            )
        ]
        if _module_available("docling"):
            checks.append(
                RuntimeCheck(
                    code="parser-docling",
                    label="Docling",
                    status="pass",
                    detail="در محیط Python نصب است.",
                )
            )
        else:
            checks.append(
                RuntimeCheck(
                    code="parser-docling",
                    label="Docling",
                    status="warning",
                    detail="نصب نیست؛ برای PDFهای پیچیده `--extra parsers` را اضافه کنید.",
                )
            )

        mineru = _command_path(self.settings.mineru_command)
        if mineru:
            checks.append(
                RuntimeCheck(
                    code="parser-mineru",
                    label="MinerU",
                    status="pass",
                    detail=f"در `{mineru}` پیدا شد.",
                )
            )
        else:
            checks.append(
                RuntimeCheck(
                    code="parser-mineru",
                    label="MinerU",
                    status="warning",
                    detail="روی PATH نیست؛ fallback محلی MinerU غیرفعال است.",
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
            return RuntimeCheck(code=code, label=label, status="pass", detail="نصب است.")
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
                detail=f"قابل نوشتن نیست: {exc}",
            )
        return RuntimeCheck(
            code=code,
            label=label,
            status="pass",
            detail=f"`{resolved}` قابل نوشتن است.",
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
