from __future__ import annotations

import hashlib
from functools import cache
from importlib import metadata
from pathlib import Path
from types import ModuleType


@cache
def module_fingerprint(*modules: ModuleType) -> str | None:
    """Identify the code that produces a parse, not just the library it wraps.

    A parser's output is decided as much by this repository's normalizers as by
    the provider they call: editing how MinerU blocks become headings changes
    every future parse, and no dependency version records that. Returns None when
    a source file cannot be read, and the caller then declines to cache -- an
    algorithm we cannot name is not one we can share.
    """

    digest = hashlib.sha256()
    for module in modules:
        source = getattr(module, "__file__", None)
        if source is None:
            return None
        try:
            digest.update(Path(source).read_bytes())
        except OSError:
            return None
        digest.update(b"\x1f")
    return digest.hexdigest()


@cache
def package_version(name: str) -> str:
    """Return an installed distribution's version, or "absent" if not installed."""

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "absent"
