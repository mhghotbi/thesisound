

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
