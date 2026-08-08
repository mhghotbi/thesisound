from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from thesisound.modeling import (
    GroundingMetadata,
    GroundingSource,
    StructuredModelResponse,
)
from thesisound.ports import RunMetadata
from thesisound.prompt_loader import PromptLoader
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner


class ExampleOutput(BaseModel):
    value: str


class GroundedFakeModel:
    provider = "fake"

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[ExampleOutput],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[ExampleOutput]:
        _ = system_prompt, user_prompt, output_type, model
        assert metadata.grounding_mode == "google_search"
        return StructuredModelResponse(
            output=ExampleOutput(value="ok"),
            provider="fake",
            model="fake",
            latency_ms=1,
            grounding=GroundingMetadata(
                mode="google_search",
                web_search_queries=["grounded query"],
                sources=[
                    GroundingSource(
                        uri="https://example.org/source",
                        title="Example",
                    )
                ],
            ),
        )


def _prompt_root(tmp_path: Path) -> Path:
    version = tmp_path / "prompts" / "example" / "1.0.0"
    version.mkdir(parents=True)
    (version / "contract.json").write_text(
        json.dumps(
            {
                "id": "example",
                "version": "1.0.0",
                "model_tier": "fast",
                "output_model": "ExampleOutput",
                "max_attempts": 1,
                "retry_schema_errors": True,
                "system_file": "system.md",
                "user_file": "user.md",
            }
        ),
        encoding="utf-8",
    )
    (version / "system.md").write_text("system", encoding="utf-8")
    (version / "user.md").write_text("{{ topic }}", encoding="utf-8")
    return tmp_path / "prompts"


def test_model_runner_persists_grounding_metadata(tmp_path: Path) -> None:
    project_id = uuid4()
    store = WorkspaceModelRunStore(tmp_path / "workspaces")
    runner = ModelRunner(
        GroundedFakeModel(),
        PromptLoader(_prompt_root(tmp_path)),
        store,
    )

    execution = runner.run(
        project_id=project_id,
        stage="query_planner",
        prompt_name="example",
        variables={"topic": "test"},
        output_type=ExampleOutput,
        model="fake",
    )

    run_dir = store.run_dir(project_id, execution.record.run_id)
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    grounding = json.loads((run_dir / "grounding.json").read_text(encoding="utf-8"))
    assert request["grounding_mode"] == "google_search"
    assert grounding["web_search_queries"] == ["grounded query"]
    assert execution.record.grounding_source_count == 1
