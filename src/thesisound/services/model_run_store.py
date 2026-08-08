from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.modeling import ModelRunRecord, PromptBundle


class WorkspaceModelRunStore:
    """Persist model-run metadata and validated outputs under a project workspace."""

    def __init__(self, workspace_root: Path, *, keep_prompts: bool = False) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.keep_prompts = keep_prompts

    def run_dir(self, project_id: UUID, run_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "model-runs" / str(run_id)

    def initialize(
        self,
        record: ModelRunRecord,
        bundle: PromptBundle,
        *,
        model: str,
        variable_names: list[str],
    ) -> Path:
        directory = self.run_dir(record.project_id, record.run_id)
        directory.mkdir(parents=True, exist_ok=False)
        request_metadata: dict[str, Any] = {
            "stage": record.stage,
            "prompt_id": bundle.contract.id,
            "prompt_version": bundle.contract.version,
            "prompt_hash": bundle.content_hash,
            "model": model,
            "output_model": bundle.contract.output_model,
            "variable_names": sorted(variable_names),
            "raw_prompts_stored": self.keep_prompts,
        }
        self._write_json(directory / "request.json", request_metadata)
        if self.keep_prompts:
            self._write_json(
                directory / "rendered-prompts.json",
                {
                    "system_prompt": bundle.system_prompt,
                    "user_prompt": bundle.user_prompt,
                },
            )
        self.save_record(record)
        return directory

    def save_record(self, record: ModelRunRecord) -> Path:
        path = self.run_dir(record.project_id, record.run_id) / "record.json"
        self._write_json(path, record.model_dump(mode="json"))
        return path

    def save_output(self, record: ModelRunRecord, output: BaseModel) -> Path:
        path = self.run_dir(record.project_id, record.run_id) / "validated-output.json"
        self._write_json(path, output.model_dump(mode="json"))
        return path

    def save_error(self, record: ModelRunRecord) -> Path:
        path = self.run_dir(record.project_id, record.run_id) / "error.json"
        self._write_json(
            path,
            {
                "error_type": record.error_type,
                "error_message": record.error_message,
                "attempts": [attempt.model_dump(mode="json") for attempt in record.attempts],
            },
        )
        return path

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
