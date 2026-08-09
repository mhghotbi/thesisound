from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.domain import EpisodePlan
from thesisound.episode import (
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodePreparationManifest,
    EpisodeStageInputs,
    SegmentEvidencePack,
)


class EpisodeArtifactStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def episode_dir(self, project_id: UUID) -> Path:
        path = self.workspace_root / str(project_id) / "episode"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def retrieval_database_path(self, project_id: UUID) -> Path:
        return self.episode_dir(project_id) / "retrieval.sqlite3"

    def save_coverage(self, report: CoverageReport) -> None:
        self._write_json(
            self.episode_dir(report.project_id) / "coverage-report.json",
            report,
        )

    def load_coverage(self, project_id: UUID) -> CoverageReport:
        return CoverageReport.model_validate_json(
            (self.episode_dir(project_id) / "coverage-report.json").read_text(
                encoding="utf-8"
            )
        )

    def save_budget(self, report: EpisodeBudgetReport) -> None:
        self._write_json(
            self.episode_dir(report.project_id) / "budget-report.json",
            report,
        )

    def load_budget(self, project_id: UUID) -> EpisodeBudgetReport:
        return EpisodeBudgetReport.model_validate_json(
            (self.episode_dir(project_id) / "budget-report.json").read_text(
                encoding="utf-8"
            )
        )

    def save_disagreement_graph(self, graph: DisagreementGraph) -> None:
        self._write_json(
            self.episode_dir(graph.project_id) / "disagreement-graph.json",
            graph,
        )

    def load_disagreement_graph(self, project_id: UUID) -> DisagreementGraph:
        return DisagreementGraph.model_validate_json(
            (self.episode_dir(project_id) / "disagreement-graph.json").read_text(
                encoding="utf-8"
            )
        )

    def save_priorities(self, report: ClaimPriorityReport) -> None:
        self._write_json(
            self.episode_dir(report.project_id) / "claim-priorities.json",
            report,
        )

    def load_priorities(self, project_id: UUID) -> ClaimPriorityReport:
        return ClaimPriorityReport.model_validate_json(
            (self.episode_dir(project_id) / "claim-priorities.json").read_text(
                encoding="utf-8"
            )
        )

    def save_plan(
        self,
        project_id: UUID,
        plan: EpisodePlan,
        draft: EpisodePlanDraft,
    ) -> None:
        directory = self.episode_dir(project_id)
        self._write_json(directory / "episode-plan.json", plan)
        self._write_json(directory / "episode-plan-draft.json", draft)

    def load_plan(self, project_id: UUID) -> EpisodePlan:
        return EpisodePlan.model_validate_json(
            (self.episode_dir(project_id) / "episode-plan.json").read_text(
                encoding="utf-8"
            )
        )

    def save_evidence_packs(
        self,
        project_id: UUID,
        packs: list[SegmentEvidencePack],
    ) -> None:
        directory = self.episode_dir(project_id) / "evidence-packs"
        directory.mkdir(parents=True, exist_ok=True)
        expected_names = {f"{pack.segment_id}.json" for pack in packs}
        for old in directory.glob("*.json"):
            if old.name not in expected_names:
                old.unlink()
        for pack in packs:
            self._write_json(directory / f"{pack.segment_id}.json", pack)
        self._write_jsonl(self.episode_dir(project_id) / "evidence-packs.jsonl", packs)

    def load_evidence_packs(self, project_id: UUID) -> list[SegmentEvidencePack]:
        path = self.episode_dir(project_id) / "evidence-packs.jsonl"
        return [
            SegmentEvidencePack.model_validate(item)
            for item in self._read_jsonl(path)
        ]

    def save_stage_inputs(self, project_id: UUID, inputs: EpisodeStageInputs) -> None:
        self._write_json(self.episode_dir(project_id) / "stage-inputs.json", inputs)

    def load_stage_inputs(self, project_id: UUID) -> EpisodeStageInputs:
        """Missing or unreadable keys mean nothing is reusable, never a hard failure."""

        path = self.episode_dir(project_id) / "stage-inputs.json"
        try:
            return EpisodeStageInputs.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return EpisodeStageInputs()

    def save_manifest(self, manifest: EpisodePreparationManifest) -> None:
        self._write_json(
            self.episode_dir(manifest.project_id) / "manifest.json",
            manifest,
        )

    def load_manifest(self, project_id: UUID) -> EpisodePreparationManifest:
        return EpisodePreparationManifest.model_validate_json(
            (self.episode_dir(project_id) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

    @staticmethod
    def _write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        payload: Any = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _write_jsonl(path: Path, values: list[BaseModel]) -> None:
        lines = [
            json.dumps(
                value.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            for value in values
        ]
        _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
