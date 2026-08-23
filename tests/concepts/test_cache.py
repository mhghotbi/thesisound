

def test_cached_paths_stay_within_the_windows_path_limit(tmp_path) -> None:
    """Two full sha256 digests overran MAX_PATH under a pytest temporary directory.

    The nested chapter path cost 134 characters before the workspace root, which put
    every chapter write past 260 on Windows and failed five tests there for reasons
    unrelated to what they were testing.
    """

    from thesisound.services.concept_map_cache import ConceptMapCache

    cache = ConceptMapCache(tmp_path)
    digest = "a" * 64
    other = "b" * 64
    relative = cache.chapter_path(digest, other).relative_to(cache.root)
    assert len(str(relative)) < 60
    assert cache.chapter_path(digest, other) != cache.chapter_path(digest, "c" * 64)
    assert cache.source_path(digest) != cache.source_path(other)


def _map(fingerprint: str, cell_count: int):
    from datetime import UTC, datetime

    from thesisound.concepts import (
        ConceptCell,
        ConceptMapStatistics,
        SourceChapter,
        SourceConceptMap,
    )
    from thesisound.services.concept_map_cache import CONCEPT_MAP_BUILDER_VERSION

    cells = [
        ConceptCell(
            cell_key=f"ch00-c{index:03d}",
            label_fa=f"مفهوم {index}",
            kind="definition",
            tier=1,
            chapter_index=0,
            section_ids=["s001"],
            block_ids=[f"b{index:04d}"],
            granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
            estimated_minutes=5.0,
        )
        for index in range(1, cell_count + 1)
    ]
    return SourceConceptMap(
        source_fingerprint=fingerprint,
        builder_version=CONCEPT_MAP_BUILDER_VERSION,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="فصل ۰",
                heading_path=["فصل ۰"],
                block_ids=[cell.block_ids[0] for cell in cells],
                estimated_minutes=5.0 * cell_count,
                detected_from="single",
                detection_agreement="agreed",
            )
        ],
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=cell_count),
        created_at=datetime.now(UTC),
    )


def test_a_second_build_does_not_replace_a_cached_map(tmp_path) -> None:
    """The module's own contract is that the map is immutable once Pass 5 succeeds.

    An unconditional write broke it: rebuilding the same source left whichever run
    finished last in the cache. In the 2026-08-23 comparison an 11-cell build was
    silently replaced by a 10-cell one, so every later project on that source would
    have inherited the worse of two builds with nothing recording the swap.
    """

    from thesisound.services.concept_map_cache import ConceptMapCache

    cache = ConceptMapCache(tmp_path)
    fingerprint = "d" * 64

    cache.save_source(_map(fingerprint, 11))
    cache.save_source(_map(fingerprint, 10))

    cached = cache.load_source(fingerprint)
    assert cached is not None
    assert len(cached.cells) == 11


def test_a_builder_version_bump_still_lets_a_fresh_map_through(tmp_path) -> None:
    """First-writer-wins must not outlive the builder version that produced it."""

    from thesisound.services import concept_map_cache as module

    cache = module.ConceptMapCache(tmp_path)
    fingerprint = "e" * 64
    cache.save_source(_map(fingerprint, 11))

    stale = _map(fingerprint, 11).model_copy(update={"builder_version": 1})
    module._atomic_write(
        cache.source_path(fingerprint),
        stale.model_dump_json(),
    )
    # The stale entry no longer loads, so the next build is free to store.
    assert cache.load_source(fingerprint) is None
    cache.save_source(_map(fingerprint, 7))
    cached = cache.load_source(fingerprint)
    assert cached is not None
    assert len(cached.cells) == 7
