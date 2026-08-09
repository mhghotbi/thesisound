from __future__ import annotations

import hashlib
import hmac
import secrets
import typing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class OtpError(ValueError):
    """User-actionable OTP error."""


class OtpSenderPort(typing.Protocol):
    def send(self, phone: str, code: str) -> None:
        """Deliver an OTP without exposing the code to the web layer."""


class NullOtpSender:
    """Development sender used before an SMS provider is connected."""

    def send(self, phone: str, code: str) -> None:
        del phone, code


@dataclass(slots=True)
class OtpChallenge:
    phone: str
    code_digest: str
    expires_at: datetime
    requested_at: datetime
    attempts: int = 0


def normalize_phone(value: str) -> str:
    normalized = value.translate(_PERSIAN_DIGITS)
    digits = "".join(character for character in normalized if character.isdigit())

    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits

    if len(digits) != 11 or not digits.startswith("09"):
        raise OtpError("شماره موبایل معتبر نیست.")
    return digits


class OtpService:
    """Small in-memory challenge store for the first local web slice.

    A durable/rate-limited store must replace this before multi-process deployment.
    """

    def __init__(
        self,
        *,
        secret: str,
        sender: OtpSenderPort,
        ttl_seconds: int = 300,
        resend_cooldown_seconds: int = 30,
        max_attempts: int = 5,
        allow_test_otp: bool = False,
        test_phone: str = "09120000000",
        test_code: str = "999999",
    ) -> None:
        self._secret = secret.encode()
        self._sender = sender
        self._ttl = timedelta(seconds=ttl_seconds)
        self._cooldown = timedelta(seconds=resend_cooldown_seconds)
        self._max_attempts = max_attempts
        self._allow_test_otp = allow_test_otp
        self._test_phone = normalize_phone(test_phone)
        self._test_code = test_code
        self._challenges: dict[str, OtpChallenge] = {}

    def _digest(self, phone: str, code: str) -> str:
        payload = f"{phone}:{code}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def request_code(self, raw_phone: str, *, now: datetime | None = None) -> str:
        phone = normalize_phone(raw_phone)
        current_time = now or datetime.now(UTC)
        existing = self._challenges.get(phone)
        if existing and current_time - existing.requested_at < self._cooldown:
            remaining = int(
                (self._cooldown - (current_time - existing.requested_at)).total_seconds()
            )
            raise OtpError(f"برای ارسال دوباره {max(1, remaining)} ثانیه صبر کنید.")

        code = (
            self._test_code
            if self._allow_test_otp and phone == self._test_phone
            else f"{secrets.randbelow(1_000_000):06d}"
        )
        self._challenges[phone] = OtpChallenge(
            phone=phone,
            code_digest=self._digest(phone, code),
            expires_at=current_time + self._ttl,
            requested_at=current_time,
        )
        self._sender.send(phone, code)
        return phone

    def verify(self, raw_phone: str, raw_code: str, *, now: datetime | None = None) -> bool:
        phone = normalize_phone(raw_phone)
        code = raw_code.translate(_PERSIAN_DIGITS).strip()
        if len(code) != 6 or not code.isdigit():
            raise OtpError("کد باید شش رقم باشد.")

        challenge = self._challenges.get(phone)
        if challenge is None:
            raise OtpError("ابتدا درخواست کد ورود بدهید.")

        current_time = now or datetime.now(UTC)
        if current_time > challenge.expires_at:
            self._challenges.pop(phone, None)
            raise OtpError("کد منقضی شده است. کد تازه بگیرید.")

        challenge.attempts += 1
        if challenge.attempts > self._max_attempts:
            self._challenges.pop(phone, None)
            raise OtpError("تعداد تلاش‌ها بیش از حد مجاز است. کد تازه بگیرید.")

        expected = challenge.code_digest
        actual = self._digest(phone, code)
        if not hmac.compare_digest(expected, actual):
            raise OtpError("کد واردشده درست نیست.")

        self._challenges.pop(phone, None)
        return True
