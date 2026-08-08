from thesisound.domain import Locator
from thesisound.quality import ParseIssue, ParseReport
from thesisound.web.source_ingestion import _quality_issue_messages, _quality_summary
from thesisound.web.source_manifest import UiSourceStatus


def test_warning_is_explained_as_non_blocking_and_actionable() -> None:
    report = ParseReport(
        verdict="warning",
        safe_for_claim_extraction=True,
        issues=[
            ParseIssue(
                issue_type="lost_headings",
                severity="medium",
                affected_locators=[Locator(page_start=12, page_end=14)],
                evidence="Heading hierarchy was flattened in three pages.",
            )
        ],
    )

    summary = _quality_summary(UiSourceStatus.READY, report)
    issues = _quality_issue_messages(report)

    assert summary is not None
    assert "قابل‌استفاده" in summary
    assert "متوقف نشده" in summary
    assert "عنوان‌ها" in issues[0]
    assert "صفحه‌های 12 تا 14" in issues[0]
