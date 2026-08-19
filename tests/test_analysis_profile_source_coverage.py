"""Conditional point 1 (`10c` P3 Step 10): `build_analysis_profile` × `lesson_intent`."""

from __future__ import annotations

from thesisound.domain import LessonIntent, Project, ProjectState, ResearchBrief, TopicType
from thesisound.services.analysis_profile import build_analysis_profile


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="موضوع",
        topic_type=TopicType.CONCEPT,
        central_question="سؤال؟",
        target_duration_minutes=duration,
    )


def _project(intent: LessonIntent) -> Project:
    return Project(raw_input="متن", state=ProjectState.CORPUS_BUILDING, lesson_intent=intent)


def test_without_a_project_short_briefs_exclude_examples_as_before() -> None:
    profile = build_analysis_profile(_brief(10))
    assert profile.include_examples is False


def test_focused_question_project_keeps_duration_driven_examples() -> None:
    profile = build_analysis_profile(
        _brief(10), project=_project(LessonIntent.FOCUSED_QUESTION)
    )
    assert profile.include_examples is False


def test_source_coverage_project_always_includes_examples() -> None:
    profile = build_analysis_profile(
        _brief(10), project=_project(LessonIntent.SOURCE_COVERAGE)
    )
    assert profile.include_examples is True
    assert any("source_coverage" in line for line in profile.rationale)
