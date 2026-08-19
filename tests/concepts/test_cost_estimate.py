from thesisound.services.cost_estimate import estimate_tokens


def test_estimate_tokens_uses_b18_multipliers() -> None:
    assert estimate_tokens(1000) == {"map": 1000, "cells": 1100, "total": 2100}


def test_estimate_tokens_zero() -> None:
    assert estimate_tokens(0) == {"map": 0, "cells": 0, "total": 0}


def test_estimate_tokens_rejects_negative() -> None:
    try:
        estimate_tokens(-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
