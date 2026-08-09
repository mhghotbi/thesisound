from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from thesisound import tracing
from thesisound.config import Settings
from thesisound.domain import SearchQuery
from thesisound.ports import RawSearchResult


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
                return self._miss(project_id)
            if payload["query_hash"] != query_hash:
                return self._miss(project_id)
            if payload["model"] != self.settings.model_fast:
                return self._miss(project_id)
            results = [RawSearchResult.model_validate(item) for item in payload["results"]]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self._miss(project_id)
        tracing.event(
            "cache.lookup",
            component="cache",
            project_id=project_id,
            cache="web_search",
            result="hit",
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
    def _miss(project_id: UUID) -> None:
        tracing.event(
            "cache.lookup",
            component="cache",
            project_id=project_id,
            cache="web_search",
            result="miss",
        )
        return None
