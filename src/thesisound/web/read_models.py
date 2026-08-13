from __future__ import annotations

from dataclasses import dataclass

from thesisound.domain import Project, ProjectState
from thesisound.web.error_messages import user_facing_error


@dataclass(frozen=True, slots=True)
class ProjectReadModel:
    project: Project
    state_label: str
    attention_label: str
    primary_action_label: str
    primary_action_url: str
    tone: str
    group_key: str
    group_label: str
    current_step: int
    requires_action: bool
    overview_summary: str
    operator_state_label: str
    technical_detail: str | None = None


_STATE_LABELS = {
    ProjectState.DRAFT: "پیش‌نویس",
    ProjectState.BRIEF_READY: "برداشت اولیه آمادهٔ بررسی است",
    ProjectState.SOURCES_COLLECTING: "در حال تکمیل منابع",
    ProjectState.SOURCE_SELECTION_REQUIRED: "منابع آمادهٔ تأییدند",
    ProjectState.CORPUS_BUILDING: "در حال تحلیل منابع",
    ProjectState.CORPUS_READY: "تحلیل منابع آماده است",
    ProjectState.EPISODE_PLANNING: "در حال سنجش کفایت منابع",
    ProjectState.EPISODE_PLANNED: "طرح گفتار آماده است",
    ProjectState.SCRIPT_DRAFTING: "در حال نوشتن متن گفتار",
    ProjectState.SCRIPT_READY: "متن گفتار آمادهٔ وارسی است",
    ProjectState.SCRIPT_VERIFYING: "در حال راستی‌آزمایی متن گفتار",
    ProjectState.SCRIPT_REVIEW_REQUIRED: "متن گفتار نیازمند بازبینی است",
    ProjectState.SCRIPT_VERIFIED: "متن گفتار تأیید شد",
    ProjectState.AUDIO_GENERATING: "در حال ساخت نسخهٔ شنیداری",
    ProjectState.AUDIO_READY: "نسخهٔ شنیداری آمادهٔ وارسی است",
    ProjectState.AUDIO_VERIFYING: "در حال وارسی شنیداری",
    ProjectState.COMPLETE: "آمادهٔ شنیدن",
    ProjectState.FAILED_RETRYABLE: "اجرا متوقف شد — قابل تلاش دوباره",
    ProjectState.FAILED_PERMANENT: "اجرا متوقف شد — نیازمند اصلاح ورودی",
}

_STEP_BY_STATE = {
    ProjectState.DRAFT: 1,
    ProjectState.BRIEF_READY: 1,
    ProjectState.SOURCES_COLLECTING: 2,
    ProjectState.SOURCE_SELECTION_REQUIRED: 2,
    ProjectState.CORPUS_BUILDING: 3,
    ProjectState.CORPUS_READY: 3,
    ProjectState.EPISODE_PLANNING: 4,
    ProjectState.EPISODE_PLANNED: 4,
    ProjectState.SCRIPT_DRAFTING: 5,
    ProjectState.SCRIPT_READY: 5,
    ProjectState.SCRIPT_VERIFYING: 5,
    ProjectState.SCRIPT_REVIEW_REQUIRED: 5,
    ProjectState.SCRIPT_VERIFIED: 5,
    ProjectState.AUDIO_GENERATING: 6,
    ProjectState.AUDIO_READY: 6,
    ProjectState.AUDIO_VERIFYING: 6,
    ProjectState.COMPLETE: 6,
    ProjectState.FAILED_RETRYABLE: 3,
    ProjectState.FAILED_PERMANENT: 3,
}


def _read_model(
    project: Project,
    *,
    attention_label: str,
    primary_action_label: str,
    primary_action_url: str,
    tone: str,
    group_key: str,
    group_label: str,
    requires_action: bool,
    overview_summary: str,
    current_step: int | None = None,
    technical_detail: str | None = None,
) -> ProjectReadModel:
    return ProjectReadModel(
        project=project,
        state_label=_STATE_LABELS[project.state],
        attention_label=attention_label,
        primary_action_label=primary_action_label,
        primary_action_url=primary_action_url,
        tone=tone,
        group_key=group_key,
        group_label=group_label,
        current_step=current_step or _STEP_BY_STATE[project.state],
        requires_action=requires_action,
        overview_summary=overview_summary,
        operator_state_label=project.state.value,
        technical_detail=technical_detail,
    )


def build_project_read_model(
    project: Project,
    *,
    failure_action_url: str | None = None,
) -> ProjectReadModel:
    project_id = str(project.project_id)

    if project.state in {ProjectState.DRAFT, ProjectState.BRIEF_READY}:
        return _read_model(
            project,
            attention_label="برداشت اولیه را بررسی و تأیید کنید",
            primary_action_label="بررسی برداشت اولیه",
            primary_action_url=f"/projects/{project_id}/brief",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "موضوع به یک پرسش اصلی و محدودهٔ اولیه تبدیل شده است؛ "
                "ادامهٔ کار به تأیید شما وابسته است."
            ),
        )

    if project.state in {
        ProjectState.SOURCES_COLLECTING,
        ProjectState.SOURCE_SELECTION_REQUIRED,
    }:
        ready = project.state == ProjectState.SOURCE_SELECTION_REQUIRED
        return _read_model(
            project,
            attention_label=(
                "منابع آماده‌اند؛ مجموعهٔ نهایی را تأیید کنید"
                if ready
                else "منبع اضافه کنید"
            ),
            primary_action_label="ادامهٔ منابع",
            primary_action_url=f"/projects/{project_id}/sources",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "حداقل یک منبع از وارسی کیفیت عبور کرده و برای انتخاب نهایی آماده است."
                if ready
                else "هنوز مجموعهٔ منابعی برای این گفتار تأیید نشده است."
            ),
        )

    if project.state == ProjectState.CORPUS_BUILDING:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن تحلیل منابع",
            primary_action_url=f"/projects/{project_id}/processing",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary=(
                "منابع منتخب در حال تبدیل‌شدن به نقشهٔ منبع، پاره‌متن‌ها، "
                "مدعاها و شاهدهای قابل‌ردیابی‌اند."
            ),
        )

    if project.state == ProjectState.CORPUS_READY:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن کفایت منابع",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary=(
                "تحلیل منابع آماده است؛ سنجش کفایت و ساخت طرح گفتار "
                "به‌صورت خودکار در صف قرار گرفته است."
            ),
        )

    if project.state == ProjectState.EPISODE_PLANNING:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن کفایت منابع",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="کفایت منابع، اختلاف دیدگاه‌ها و مدت قابل‌پشتیبانی در حال سنجش است.",
        )

    if project.state == ProjectState.EPISODE_PLANNED:
        return _read_model(
            project,
            attention_label="ساختار گفتار را بررسی و تأیید کنید",
            primary_action_label="بررسی طرح گفتار",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "طرح گفتار بر پایهٔ بسندگی شاهدها ساخته‌شده و برای تأیید انسانی آماده است."
            ),
        )

    if project.state in {
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.SCRIPT_READY,
        ProjectState.SCRIPT_VERIFYING,
    }:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن متن گفتار",
            primary_action_url=f"/projects/{project_id}/script",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="متن گفتار در حال نگارش، وارسی ساختاری و راستی‌آزمایی مستقل است.",
        )

    if project.state == ProjectState.SCRIPT_REVIEW_REQUIRED:
        return _read_model(
            project,
            attention_label="متن گفتار نیازمند بازبینی است",
            primary_action_label="ساخت صدا یا بازنویسی",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "راستی‌آزمایی نکته‌ای غیرمسدودکننده باقی گذاشته است؛ "
                "یادداشت‌ها روی صفحهٔ ساخت صدا نمایش داده می‌شوند."
            ),
        )

    if project.state == ProjectState.SCRIPT_VERIFIED:
        return _read_model(
            project,
            attention_label="متن گفتار آمادهٔ ساخت نسخهٔ شنیداری است",
            primary_action_label="ساخت نسخهٔ شنیداری",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "همهٔ گفته‌های محتوایی از وارسی ساختاری و راستی‌آزمایی مستقل عبور کرده‌اند."
            ),
        )

    if project.state in {
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_READY,
        ProjectState.AUDIO_VERIFYING,
    }:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن نسخهٔ شنیداری",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="قطعه‌های صوتی در حال ساخت، رونویسی و مقایسه با متن گفتارند.",
        )

    if project.state in {ProjectState.FAILED_RETRYABLE, ProjectState.FAILED_PERMANENT}:
        destination = failure_action_url or f"/projects/{project_id}/processing"
        retryable = project.state == ProjectState.FAILED_RETRYABLE
        return _read_model(
            project,
            attention_label=(
                "اجرا متوقف شده و امکان تلاش دوباره وجود دارد"
                if retryable
                else "برای ادامه باید ورودی یا محیط اجرا اصلاح شود"
            ),
            primary_action_label="بررسی مشکل",
            primary_action_url=destination,
            tone="danger",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=user_facing_error(project.last_error, action="generic"),
            technical_detail=project.last_error,
        )

    if project.state == ProjectState.COMPLETE:
        return _read_model(
            project,
            attention_label="گفتار آمادهٔ شنیدن است",
            primary_action_label="شنیدن گفتار",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="success",
            group_key="complete",
            group_label="آمادهٔ شنیدن",
            requires_action=False,
            overview_summary="نسخهٔ شنیداری، متن همگام و مسیر ردیابی شاهدها آماده‌اند.",
        )

    return _read_model(
        project,
        attention_label="فرایند در حال انجام است",
        primary_action_label="مشاهدهٔ وضعیت",
        primary_action_url=f"/projects/{project_id}/processing",
        tone="running",
        group_key="running",
        group_label="در حال انجام",
        requires_action=False,
        overview_summary="گفتار از آخرین مرحلهٔ معتبر ادامه پیدا می‌کند.",
    )
