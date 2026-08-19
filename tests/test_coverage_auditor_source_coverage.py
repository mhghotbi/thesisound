"""Conditional point 3 (`10c` P3 Step 10): `can_plan_episode` × `lesson_intent`."""

from __future__ import annotations

from thesisound.domain import LessonIntent
from thesisound.services.coverage_auditor import can_plan_episode


def test_without_lesson_intent_the_80_percent_gate_applies_as_before() -> None:
    assert can_plan_episode(
        recommendation="continue", max_supported_minutes=7, target_duration_minutes=10
    ) is False
    assert can_plan_episode(
        recommendation="continue", max_supported_minutes=8, target_duration_minutes=10
    ) is True


def test_focused_question_keeps_the_80_percent_gate() -> None:
    assert can_plan_episode(
        recommendation="continue",
        max_supported_minutes=7,
        target_duration_minutes=10,
        lesson_intent=LessonIntent.FOCUSED_QUESTION,
    ) is False


def test_source_coverage_ignores_the_80_percent_gate_but_not_the_recommendation() -> None:
    assert can_plan_episode(
        recommendation="continue",
        max_supported_minutes=1,
        target_duration_minutes=200,
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
    ) is True
    assert can_plan_episode(
        recommendation="narrow_scope",
        max_supported_minutes=200,
        target_duration_minutes=10,
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
    ) is False
