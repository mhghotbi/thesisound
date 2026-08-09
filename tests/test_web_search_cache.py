from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from thesisound.config import Settings
from thesisound.domain import SearchQuery, SourceRole
from thesisound.ports import RawSearchResult
from thesisound.services.web_search_cache import WebSearchCache


def _settings(tmp_path: Path, *, model: str = "model-a") -> Settings:
    return Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        model_fast=model,
        http_proxy="none",
    )


def _query(value: str = "ethics") -> SearchQuery:
    return SearchQuery(
        query=value,
        provider="web",
        source_role=SourceRole.REFERENCE,
        language="fa",
        purpose="test",
        priority=3,
    )


def _results() -> list[RawSearchResult]:
    return [
        RawSearchResult(
            provider="fake",
            title="Result",
            url="https://example.com/result",
            snippet_or_abstract="snippet",
        )
    ]


def test_miss_save_hit_round_trip(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()

    assert cache.load(project_id, query) is None
    cache.save(query, _results())
    assert cache.load(project_id, query) == _results()


def test_expired_entry_is_a_miss(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()
    cache.save(query, _results())
    frozen_clock.advance((settings.web_search_cache_ttl_hours + 1) * 3600)

    assert cache.load(project_id, query) is None


def test_corrupt_json_is_a_miss(tmp_path: Path, frozen_clock) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    query = _query()
    path = cache.path_for(query)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"truncated":', encoding="utf-8")

    assert cache.load(uuid4(), query) is None


def test_query_and_model_are_part_of_the_key(tmp_path: Path, frozen_clock) -> None:
    settings_a = _settings(tmp_path, model="model-a")
    cache_a = WebSearchCache(settings_a.workspace_root, settings_a, now=frozen_clock.now)
    cache_a.save(_query("one"), _results())

    assert cache_a.load(uuid4(), _query("two")) is None
    settings_b = _settings(tmp_path, model="model-b")
    cache_b = WebSearchCache(settings_b.workspace_root, settings_b, now=frozen_clock.now)
    assert cache_b.load(uuid4(), _query("one")) is None
    assert cache_a.path_for(_query("one")) != cache_b.path_for(_query("one"))


def test_cache_lookup_events_report_hit_and_miss(
    tmp_path: Path,
    frozen_clock,
    recording_tracer,
) -> None:
    settings = _settings(tmp_path)
    cache = WebSearchCache(settings.workspace_root, settings, now=frozen_clock.now)
    project_id = uuid4()
    query = _query()
    cache.load(project_id, query)
    cache.save(query, _results())
    cache.load(project_id, query)

    events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "web_search"
    ]
    assert [event.attributes["result"] for event in events] == ["miss", "hit"]
