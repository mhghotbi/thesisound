from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.adapters.models.okian import OkianHttpResponse, OkianStructuredModel
from thesisound.config import Settings
from thesisound.modeling import ModelProviderError, ModelUsage, StructuredModelResponse
from thesisound.observability import ObservabilityLedger
from thesisound.ports import RunMetadata


class ExampleOutput(BaseModel):
    answer: str


class RateLimitException(RuntimeError):
    status_code = 429


class DisconnectException(RuntimeError):
    """Simulates a mid-flight provider disconnect (no HTTP status)."""


class FakeModels:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        raise AssertionError("Gemini should not succeed in these tests")


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class RecordingOkianPort:
    def __init__(self, response: StructuredModelResponse[ExampleOutput]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOkianClient:
    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, object], float]] = []

    def create_chat_completion(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> OkianHttpResponse:
        self.requests.append((payload, timeout_seconds))
        return OkianHttpResponse(
            payload={
                "id": "req-okian-fallback",
                "model": payload["model"],
                "choices": [
                    {
                        "message": {"content": '{"answer":"from-okian"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
            status_code=200,
            headers={},
        )


def _settings(tmp_path: Path, *, with_okian: bool) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "workspace_root": tmp_path / "workspaces",
        "observability_database_path": tmp_path / "ledger.sqlite3",
        "observability_artifact_root": tmp_path / "artifacts",
        # Explicit empties beat process env; otherwise Okian stays "configured".
        "okian_base_url": "",
        "okian_api_key": "",
    }
    if with_okian:
        kwargs["okian_base_url"] = "https://okian.example/v1"
        kwargs["okian_api_key"] = "test-okian-key"
    return Settings(**kwargs)


def test_ungrounded_rate_limit_falls_back_to_okian_with_same_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_okian=True)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    gemini_call_id = uuid4()
    models = FakeModels(error=RateLimitException("quota exhausted"))
    adapter = GeminiStructuredModel(
        client=FakeClient(models),
        settings=settings,
        observability=ledger,
    )
    okian_client = FakeOkianClient()
    adapter._okian_port = OkianStructuredModel(
        client=okian_client,
        settings=settings,
        observability=ledger,
    )

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="gemini-3.5-flash-lite",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="gemini-3.5-flash-lite",
            provider="gemini",
            model_profile="gemini_fast",
            call_id=gemini_call_id,
            project_id=uuid4(),
        ),
    )

    assert response.provider == "okian"
    assert response.output.answer == "from-okian"
    assert response.call_id != gemini_call_id
    assert len(okian_client.requests) == 1
    assert okian_client.requests[0][0]["model"] == "gemini-3.5-flash-lite"

    failed = ledger.get_call(gemini_call_id)
    assert failed.call.provider == "gemini"
    assert failed.call.status == "failed"

    succeeded = ledger.get_call(response.call_id)
    assert succeeded.call.provider == "okian"
    assert succeeded.call.status == "succeeded"
    assert succeeded.parent_call_id == gemini_call_id
    assert succeeded.metadata["okian_fallback_from"] == "gemini"


def test_ungrounded_provider_disconnect_falls_back_to_okian(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_okian=True)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    gemini_call_id = uuid4()
    models = FakeModels(error=DisconnectException("Server disconnected without sending a response."))
    adapter = GeminiStructuredModel(
        client=FakeClient(models),
        settings=settings,
        observability=ledger,
    )
    okian_client = FakeOkianClient()
    adapter._okian_port = OkianStructuredModel(
        client=okian_client,
        settings=settings,
        observability=ledger,
    )

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="gemini-3.6-flash",
        metadata=RunMetadata(
            stage="claim_reconciliation",
            model_or_provider="gemini-3.6-flash",
            provider="gemini",
            model_profile="gemini_strong",
            call_id=gemini_call_id,
            project_id=uuid4(),
        ),
    )

    assert response.provider == "okian"
    assert response.output.answer == "from-okian"
    assert len(okian_client.requests) == 1
    assert okian_client.requests[0][0]["model"] == "gemini-3.6-flash"
    succeeded = ledger.get_call(response.call_id)
    assert succeeded.parent_call_id == gemini_call_id
    assert succeeded.metadata["okian_fallback_from"] == "gemini"


def test_grounded_errors_do_not_fall_back_to_okian(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_okian=True)
    models = FakeModels(error=DisconnectException("Server disconnected without sending a response."))
    adapter = GeminiStructuredModel(
        client=FakeClient(models),
        settings=settings,
    )
    recording = RecordingOkianPort(
        StructuredModelResponse(
            output=ExampleOutput(answer="unused"),
            provider="okian",
            model="gemini-3.5-flash-lite",
            usage=ModelUsage(),
            latency_ms=1,
            call_id=uuid4(),
        )
    )
    adapter._okian_port = recording

    with pytest.raises(ModelProviderError, match="Server disconnected"):
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Search.",
            output_type=ExampleOutput,
            model="gemini-3.5-flash-lite",
            metadata=RunMetadata(
                stage="research_brief",
                model_or_provider="gemini-3.5-flash-lite",
                grounding_mode="google_search",
            ),
        )

    assert recording.calls == []


def test_error_without_okian_credentials_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_okian=False)
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=DisconnectException("Server disconnected"))),
        settings=settings,
    )

    with pytest.raises(ModelProviderError, match="Server disconnected"):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=RunMetadata(stage="document_map", model_or_provider="gemini-test"),
        )


def test_explicit_okian_provider_does_not_double_fallback(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_okian=True)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    models = FakeModels(error=RateLimitException("should not be called"))
    adapter = GeminiStructuredModel(
        client=FakeClient(models),
        settings=settings,
        observability=ledger,
    )
    okian_client = FakeOkianClient()
    adapter._okian_port = OkianStructuredModel(
        client=okian_client,
        settings=settings,
        observability=ledger,
    )

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="gemini-3.5-flash-lite",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="gemini-3.5-flash-lite",
            provider="okian",
            model_profile="okian_gemini_fast",
        ),
    )

    assert response.provider == "okian"
    assert response.output.answer == "from-okian"
    assert models.calls == []
    assert len(okian_client.requests) == 1
    detail = ledger.get_call(response.call_id)
    assert detail.metadata.get("okian_fallback_from") is None
