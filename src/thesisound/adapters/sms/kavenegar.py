"""Kavenegar verify/lookup adapter for OTP SMS delivery."""

from __future__ import annotations

import logging
from typing import Any

from kavenegar import APIException, HTTPException, KavenegarAPI

logger = logging.getLogger(__name__)


class KavenegarError(RuntimeError):
    """Raised when Kavenegar rejects or fails an OTP send."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_status = provider_status


class KavenegarOtpSender:
    """Deliver OTP codes through Kavenegar's ``verify/lookup`` API."""

    def __init__(
        self,
        *,
        api_key: str,
        template: str,
        message_type: str = "sms",
        client: KavenegarAPI | None = None,
    ) -> None:
        key = api_key.strip()
        template_name = template.strip()
        if not key:
            raise ValueError("KAVENEGAR_API_KEY is required.")
        if not template_name:
            raise ValueError("KAVENEGAR_TEMPLATE_NAME is required.")

        self._template = template_name
        self._message_type = message_type.strip() or "sms"
        self._client = client or KavenegarAPI(key)

    def send(self, phone: str, code: str) -> None:
        token = code.strip()
        if not phone.strip():
            raise KavenegarError("OTP receptor phone is empty.")
        if not token or " " in token:
            raise KavenegarError("OTP token must be non-empty and contain no spaces.")
        if len(token) > 100:
            raise KavenegarError("OTP token exceeds Kavenegar's 100-character limit.")

        params = {
            "receptor": phone.strip(),
            "token": token,
            "template": self._template,
            "type": self._message_type,
        }
        try:
            entries = self._client.verify_lookup(params)
        except APIException as exc:
            raise KavenegarError(
                f"Kavenegar rejected OTP send: {_exception_text(exc)}",
                provider_status=_provider_status_from_api_exception(exc),
            ) from exc
        except HTTPException as exc:
            raise KavenegarError(
                f"Kavenegar request failed: {_exception_text(exc)}"
            ) from exc

        entry = _first_entry(entries)
        message_id = entry.get("messageid") if entry is not None else None
        logger.info(
            "kavenegar_otp_sent",
            extra={
                "receptor_suffix": phone.strip()[-4:],
                "message_id": message_id,
                "template": self._template,
            },
        )


def _first_entry(entries: Any) -> dict[str, Any] | None:
    if isinstance(entries, list) and entries:
        first = entries[0]
        return first if isinstance(first, dict) else None
    if isinstance(entries, dict):
        return entries
    return None


def _exception_text(exc: BaseException) -> str:
    raw = getattr(exc, "args", ())
    if not raw:
        return str(exc) or exc.__class__.__name__
    value = raw[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _provider_status_from_api_exception(exc: APIException) -> int | None:
    text = _exception_text(exc)
    # Official SDK formats: "APIException[424] الگو یافت نشد"
    if "APIException[" not in text:
        return None
    try:
        start = text.index("[") + 1
        end = text.index("]", start)
        return int(text[start:end])
    except (ValueError, IndexError):
        return None
