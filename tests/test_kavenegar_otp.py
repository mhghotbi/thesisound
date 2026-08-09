from __future__ import annotations

from typing import Any

import pytest
from kavenegar import APIException, HTTPException

from thesisound.adapters.sms.kavenegar import KavenegarError, KavenegarOtpSender
from thesisound.web.auth import OtpError, OtpService


class FakeKavenegarClient:
    def __init__(
        self,
        *,
        response: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, str]] = []

    def verify_lookup(self, params: dict[str, str] | None = None) -> Any:
        self.calls.append(dict(params or {}))
        if self.error is not None:
            raise self.error
        return self.response


def test_kavenegar_sender_calls_verify_lookup() -> None:
    client = FakeKavenegarClient(
        response=[{"messageid": 8792343, "receptor": "09121234567"}]
    )
    sender = KavenegarOtpSender(api_key="test-key", template="aist", client=client)

    sender.send("09121234567", "123456")

    assert client.calls == [
        {
            "receptor": "09121234567",
            "token": "123456",
            "template": "aist",
            "type": "sms",
        }
    ]


def test_kavenegar_sender_maps_api_exception() -> None:
    client = FakeKavenegarClient(
        error=APIException("APIException[424] الگو یافت نشد".encode("utf-8"))
    )
    sender = KavenegarOtpSender(api_key="test-key", template="aist", client=client)

    with pytest.raises(KavenegarError, match="الگو یافت نشد") as caught:
        sender.send("09121234567", "123456")
    assert caught.value.provider_status == 424


def test_kavenegar_sender_maps_http_exception() -> None:
    client = FakeKavenegarClient(error=HTTPException("network down"))
    sender = KavenegarOtpSender(api_key="test-key", template="aist", client=client)

    with pytest.raises(KavenegarError, match="network down"):
        sender.send("09121234567", "123456")


def test_otp_service_does_not_store_challenge_when_send_fails() -> None:
    class BoomSender:
        def send(self, phone: str, code: str) -> None:
            del phone, code
            raise RuntimeError("sms down")

    service = OtpService(secret="test-secret", sender=BoomSender(), allow_test_otp=False)
    with pytest.raises(OtpError, match="ناموفق"):
        service.request_code("09121234567")

    with pytest.raises(OtpError, match="ابتدا درخواست"):
        service.verify("09121234567", "123456")
