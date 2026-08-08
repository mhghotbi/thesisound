from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.okian import OkianHttpResponse, OkianStructuredModel
from thesisound.config import Settings
from thesisound.modeling import ModelConfigurationError
from thesisound.observability import ObservabilityLedger
from thesisound.ports import RunMetadata


class ExampleOutput(BaseModel):
    answer: str


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
                "id": "req-okian-1",
                "model": "qwen-private-id",
                "choices": [
                    {
                        "message": {"content": '{"answer":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
            status_code=200,
            headers={"x-request-id": "req-okian-1"},
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "ledger.sqlite3",
        observability_artifact_root=tmp_path / "artifacts",
    )


def test_okian_structured_output_is_observed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    client = FakeOkianClient()
    project_id = uuid4()
    adapter = OkianStructuredModel(
        client=client,
        observability=ledger,
        settings=settings,
    )

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="qwen-private-id",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="qwen-private-id",
            provider="okian",
            model_profile="okian_qwen",
            project_id=project_id,
        ),
    )

    assert response.output.answer == "ok"
    assert response.provider == "okian"
    assert response.model == "qwen-private-id"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 4
    assert response.usage.thinking_tokens == 2
    assert response.usage.cached_tokens == 3
    assert client.requests[0][0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "ExampleOutput",
            "strict": True,
            "schema": ExampleOutput.model_json_schema(),
        },
    }

    detail = ledger.get_call(response.call_id)
    assert detail.call.provider == "okian"
    assert detail.call.status == "succeeded"
    assert detail.call.total_tokens == 15
    assert detail.metadata["model_profile"] == "okian_qwen"


def test_okian_refuses_gemini_grounding_before_http(tmp_path: Path) -> None:
    client = FakeOkianClient()
    adapter = OkianStructuredModel(
        client=client,
        settings=_settings(tmp_path),
    )

    with pytest.raises(ModelConfigurationError, match="Google Search"):
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="qwen-private-id",
            metadata=RunMetadata(
                stage="source_discovery",
                model_or_provider="qwen-private-id",
                provider="okian",
                grounding_mode="google_search",
            ),
        )

    assert client.requests == []
