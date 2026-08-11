from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from thesisound.config import Settings
from thesisound.domain import SearchQuery
from thesisound.ports import RawSearchResult
from thesisound.services.lineage_events import emit_cache_lookup


class WebSearchCache:
    def __init__(
        self,
        workspace_root: Path,
        settings: Settings,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = workspace_root / "_shared" / "web-search"
        self.settings = settings
        self.now = now or (lambda: datetime.now(UTC))

    def load(
        self,
        project_id: UUID,
        query: SearchQuery,
    ) -> list[RawSearchResult] | None:
        query_hash = self._query_hash(query)
        path = self.root / f"{query_hash}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if self.now() - created_at > timedelta(
                hours=self.settings.web_search_cache_ttl_hours
            ):
                return self._miss(
                    project_id,
                    query_hash=query_hash,
                    invalidation_reason="ttl_expired",
                )
            if payload["query_hash"] != query_hash:
                return self._miss(
                    project_id,
                    query_hash=query_hash,
                    invalidation_reason="query_hash_mismatch",
                )
            if payload["model"] != self.settings.model_fast:
                return self._miss(
                    project_id,
                    query_hash=query_hash,
                    invalidation_reason="model_mismatch",
                )
            results = [RawSearchResult.model_validate(item) for item in payload["results"]]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self._miss(project_id, query_hash=query_hash)
        emit_cache_lookup(
            cache="web_search",
            result="hit",
            project_id=project_id,
            lookup_key=query_hash[:16],
            artifact_id=path.name,
            avoided_calls=1,
        )
        return results

    def save(self, query: SearchQuery, results: list[RawSearchResult]) -> None:
        query_hash = self._query_hash(query)
        path = self.root / f"{query_hash}.json"
        temporary = path.with_suffix(".json.tmp")
        payload = {
            "created_at": self.now().isoformat(),
            "query_hash": query_hash,
            "model": self.settings.model_fast,
            "results": [item.model_dump(mode="json") for item in results],
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            return

    def path_for(self, query: SearchQuery) -> Path:
        return self.root / f"{self._query_hash(query)}.json"

    def _query_hash(self, query: SearchQuery) -> str:
        payload = json.dumps(
            {
                "query": query.model_dump(mode="json"),
                "model": self.settings.model_fast,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _miss(
        project_id: UUID,
        *,
        query_hash: str | None = None,
        invalidation_reason: str | None = None,
    ) -> None:
        emit_cache_lookup(
            cache="web_search",
            result="miss",
            project_id=project_id,
            lookup_key=query_hash[:16] if query_hash else None,
            invalidation_reason=invalidation_reason,
        )
        return None
