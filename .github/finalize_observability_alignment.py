from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/thesisound/observability.py",
    '''def _hashed_sensitive_value(value: Any) -> dict[str, Any]:
    text = _sensitive_text(value)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "length": len(text),
    }
''',
    '''def _hashed_sensitive_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        digest = value.get("sha256")
        length = value.get("length")
        if (
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
            and isinstance(length, int)
            and not isinstance(length, bool)
            and length >= 0
        ):
            return {"sha256": digest, "length": length}

    text = _sensitive_text(value)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "length": len(text),
    }
''',
)

replace_once(
    "src/thesisound/web/observability_routes.py",
    '''    Authorization is based on the authenticated account role, never the UI
    preference stored in ``session['ui_mode']``. The latter only controls how
    much technical information normal workflow pages choose to render.
''',
    '''    Authorization requires the authenticated account role to be ``operator``.
    The existing ``session['ui_mode'] == 'operator'`` preference is an additional
    presentation gate; it never grants authorization by itself.
''',
)

replace_once(
    "tests/test_observability.py",
    '''    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
)''',
    '''    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
    redact_value,
)''',
)

replace_once(
    "tests/test_observability.py",
    '''    assert second["query"]["sha256"] == stored["query"]["sha256"]
    assert second["filename"]["filename_sha256"] == stored["filename"]["filename_sha256"]

    payloads = ObservabilityLedger(''',
    '''    assert second["query"]["sha256"] == stored["query"]["sha256"]
    assert second["filename"]["filename_sha256"] == stored["filename"]["filename_sha256"]
    assert redact_value({"query": stored["query"]}, store_payloads=False)["query"] == stored[
        "query"
    ]

    payloads = ObservabilityLedger(''',
)
