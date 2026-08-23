"""A process that never installs a tracer must not fail silently."""

from __future__ import annotations

import logging

import pytest

from thesisound import tracing


@pytest.fixture(autouse=True)
def _restore_tracer_state():
    saved = (tracing._TRACER, tracing._TRACER_INSTALLED, tracing._WARNED_UNINSTALLED)
    yield
    tracing._TRACER, tracing._TRACER_INSTALLED, tracing._WARNED_UNINSTALLED = saved


def test_an_uninstalled_tracer_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    """The 2026-08-23 forensics stalled here.

    Both comparison runs left `model_calls` and `linkage.incomplete` -- both
    written straight to SQLite -- but zero `pipeline_spans` and zero
    `cache.lookup`, which go through the ambient tracer. That reads like a code
    path that never ran, when in fact telemetry was never wired.
    """

    tracing._TRACER_INSTALLED = False
    tracing._WARNED_UNINSTALLED = False

    with caplog.at_level(logging.WARNING):
        tracing.warn_if_no_tracer_installed()
        tracing.warn_if_no_tracer_installed()

    warnings = [r for r in caplog.records if "No tracer installed" in r.message]
    assert len(warnings) == 1


def test_an_installed_tracer_is_silent_even_when_disabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracing switched off in settings is a decision, not an oversight."""

    tracing._WARNED_UNINSTALLED = False
    tracing.install_tracer(tracing.Tracer(tracing.NullSpanSink(), enabled=False))

    with caplog.at_level(logging.WARNING):
        tracing.warn_if_no_tracer_installed()

    assert not [r for r in caplog.records if "No tracer installed" in r.message]
    assert tracing.tracer_installed() is True


def test_install_tracer_from_settings_wires_the_ambient_tracer(tmp_path) -> None:
    """One call, so an entry point cannot wire half of it."""

    from thesisound.config import Settings
    from thesisound.observability import install_tracer_from_settings

    tracing._TRACER_INSTALLED = False
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "ledger.sqlite3",
        observability_artifact_root=tmp_path / "artifacts",
    )

    built = install_tracer_from_settings(settings)

    assert tracing.tracer() is built
    assert tracing.tracer_installed() is True
