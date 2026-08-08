from __future__ import annotations

from dataclasses import dataclass

from thesisound.domain import Project, ProjectState


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
    ProjectState.BRIEF_READY: "برداشت آماده بررسی",
    ProjectState.SOURCES_COLLECTING: "در حال تکمیل منابع",
    ProjectState.SOURCE_SELECTION_REQUIRED: "منابع آماده تأیید",
    ProjectState.CORPUS_BUILDING: "در حال استخراج شواهد",
    ProjectState.CORPUS_READY: "مجموعه شواهد آماده",
    ProjectState.EPISODE_PLANNING: "در حال ارزیابی پوشش",
    ProjectState.EPISODE_PLANNED: "طرح اپیزود آماده",
    ProjectState.SCRIPT_DRAFTING: "در حال نوشتن متن اپیزود",
    ProjectState.SCRIPT_READY: "متن آماده کنترل",
    ProjectState.SCRIPT_VERIFYING: "در حال راستی‌آزمایی متن",
    ProjectState.SCRIPT_VERIFIED: "متن اپیزود تأیید شد",
    ProjectState.AUDIO_GENERATING: "در حال تولید صدا",
    ProjectState.AUDIO_READY: "صدا آماده کنترل",
    ProjectState.AUDIO_VERIFYING: "در حال کنترل شنیداری",
    ProjectState.COMPLETE: "آماده شنیدن",
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
            attention_label="برداشت سیستم را بررسی و تأیید کنید",
            primary_action_label="بررسی برداشت",
            primary_action_url=f"/projects/{project_id}/brief",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "موضوع به یک سؤال مرکزی و محدوده اولیه تبدیل شده است؛ "
                "ادامه کار به تأیید شما وابسته است."
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
                "منابع آماده‌اند؛ مجموعه نهایی را تأیید کنید"
                if ready
                else "منبع اضافه کنید یا جست‌وجوی وب را اجرا کنید"
            ),
            primary_action_label="ادامه منابع",
            primary_action_url=f"/projects/{project_id}/sources",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "حداقل یک منبع از کنترل کیفیت عبور کرده و برای انتخاب نهایی آماده است."
                if ready
                else "هنوز مجموعه‌ای که بتواند مبنای شواهد اپیزود باشد تأیید نشده است."
            ),
        )

    if project.state == ProjectState.CORPUS_BUILDING:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن پردازش",
            primary_action_url=f"/projects/{project_id}/processing",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary=(
                "منابع انتخاب‌شده در حال تبدیل‌شدن به بلوک‌های معنایی، "
                "شواهد و ادعاهای قابل‌ردیابی‌اند."
            ),
        )

    if project.state == ProjectState.CORPUS_READY:
        return _read_model(
            project,
            attention_label="پوشش منابع را ارزیابی و ساخت طرح را شروع کنید",
            primary_action_label="رفتن به طرح اپیزود",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "مجموعه شواهد آماده است؛ حالا باید روشن شود "
                "چه مدت محتوای معتبر پشتیبانی می‌شود."
            ),
        )

    if project.state == ProjectState.EPISODE_PLANNING:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن ارزیابی پوشش",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="پوشش منابع، اختلاف دیدگاه‌ها و بودجه محتوایی در حال ارزیابی است.",
        )

    if project.state == ProjectState.EPISODE_PLANNED:
        return _read_model(
            project,
            attention_label="ساختار اپیزود را بررسی و تأیید کنید",
            primary_action_label="بررسی طرح اپیزود",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary=(
                "طرح اپیزود بر اساس سقف شواهد موجود ساخته شده و "
                "برای تأیید انسانی آماده است."
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
            primary_action_label="دیدن متن اپیزود",
            primary_action_url=f"/projects/{project_id}/script",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="متن اپیزود در حال نگارش، کنترل قطعی و راستی‌آزمایی مستقل است.",
        )

    if project.state == ProjectState.SCRIPT_VERIFIED:
        return _read_model(
            project,
            attention_label="متن تأییدشده آماده تولید صوت است",
            primary_action_label="ساخت صوت",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="attention",
            group_key="attention",
            group_label="منتظر شما",
            requires_action=True,
            overview_summary="همه turnهای محتوایی از کنترل قطعی و verifier عبور کرده‌اند.",
        )

    if project.state in {
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_READY,
        ProjectState.AUDIO_VERIFYING,
    }:
        return _read_model(
            project,
            attention_label="اقدامی از شما لازم نیست",
            primary_action_label="دیدن تولید صوت",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="running",
            group_key="running",
            group_label="در حال انجام",
            requires_action=False,
            overview_summary="قطعه‌های صوتی در حال تولید، رونویسی و مقایسه با متن تأییدشده‌اند.",
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
            overview_summary=(
                "آخرین artifactهای سالم باقی مانده‌اند و فقط مرحله ناموفق "
                "نیازمند اقدام است."
            ),
            technical_detail=project.last_error,
        )

    if project.state == ProjectState.COMPLETE:
        return _read_model(
            project,
            attention_label="اپیزود کنترل‌شده آماده شنیدن است",
            primary_action_label="گوش دادن",
            primary_action_url=f"/projects/{project_id}/audio",
            tone="success",
            group_key="complete",
            group_label="آماده و بایگانی‌شده",
            requires_action=False,
            overview_summary="فایل نهایی، transcript و مسیر ردیابی شواهد آماده‌اند.",
        )

    return _read_model(
        project,
        attention_label="فرایند در حال انجام است",
        primary_action_label="مشاهده وضعیت",
        primary_action_url=f"/projects/{project_id}/processing",
        tone="running",
        group_key="running",
        group_label="در حال انجام",
        requires_action=False,
        overview_summary="پروژه از آخرین artifact معتبر ادامه پیدا می‌کند.",
    )
