# Private holdout boundary

This public directory contains only the opaque manifest and its schema. The three
slots are intentionally unprovisioned: no source, topic, brief, failure-mode
description, expected atom, fixture text, or gold exists here.

A private bundle must live outside `benchmarks/eval` and use this interface:

```text
<external-private-bundle>/
  gates.toml
  cases/
    <opaque-id>/
      case.toml
      expectations.toml
      sources/
        <private fixture files>
```

Core is the default and never resolves a private path:

```powershell
thesisound eval --split core --dry-run
```

A holdout operator must opt in and name the external bundle explicitly:

```powershell
thesisound eval --split holdout --private-bundle <external-private-bundle>
```

The runner rejects private bundles placed beneath the public `benchmarks/eval`
tree. Public reporting may update only the opaque hashes, schema/evaluator version,
last-run metadata, and an aggregate result. Semantic per-case data stays private.
