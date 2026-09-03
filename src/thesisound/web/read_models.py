from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from thesisound.domain import DeliveryMode, Project, ProjectState
from thesisound.web.error_messages import user_facing_error
from thesisound.web.readiness_views import ReadinessView

#: How the produced work is doing. Drives shape and colour, nothing else.
Health = Literal["success", "warning", "danger", "neutral"]

#: Whose move it is next. Drives grouping and button prominence, nothing else.
Ownership = Literal["you", "system", "none"]


@dataclass(frozen=True, slots=True)
class ProjectReadModel:
    """Two independent axes, because one `tone` could not carry both.

    `tone` used to mean "the output is healthy" and "this needs you" at the same
    time, and the visual vocabulary only understands the first. So `SCRIPT_VERIFIED`
    — a state that means every claim survived independent verification — was drawn
    with a warning triangle in `--warning`, next to the words "متن گفتار تأیید شد".
    Shape said problem, colour said warning, the sentence said verified.

    `health` owns the mark and the colour. `ownership` owns the grouping and whether
    the row's action reads as primary. Neither one can quietly stand in for the other.
    """

    project: Project
    state_label: str
    attention_label: str
    primary_action_label: str
    primary_action_url: str
    health: Health
    ownership: Ownership
    group_key: str
    group_label: str
    current_step: int
    overview_summary: str
    operator_state_label: str
    technical_detail: str | None = None

    @property
    def requires_action(self) -> bool:
        return self.ownership == "you"

    @property
    def status_tone(self) -> str:
        """The single vocabulary `status_label` speaks, composed from the two axes.

        Derived, never stored — and that is the whole difference from the `tone` this
        replaced. Flattening happens here, at the one place a single mark has to be
        drawn, and both axes survive it: motion says the system is working, the
        triangle says the work wants attention, and neither can silently become the
        other upstream.
        """
        if self.health == "danger":
            return "danger"
        if self.ownership == "system":
            return "running"
        return "attention" if self.health == "warning" else self.health


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


def state_label_for(state: ProjectState) -> str:
    """The reader-facing name of a state, for callers holding a state and no project."""
    return _STATE_LABELS[state]


def _state_label(project: Project) -> str:
    # `delivery == text` reaches COMPLETE straight from SCRIPT_VERIFIED (no audio
    # stage) and its written lesson is read, not listened to.
    if project.state == ProjectState.COMPLETE and project.delivery == DeliveryMode.TEXT:
        return "متن گفتار آمادهٔ خواندن است"
    return _STATE_LABELS[project.state]


def _read_model(
    project: Project,
    *,
    attention_label: str,
    primary_action_label: str,
    primary_action_url: str,
    health: Health,
    ownership: Ownership,
    group_key: str,
    group_label: str,
    overview_summary: str,
    current_step: int | None = None,
    technical_detail: str | None = None,
) -> ProjectReadModel:
    return ProjectReadModel(
        project=project,
        state_label=_state_label(project),
        attention_label=attention_label,
        primary_action_label=primary_action_label,
        primary_action_url=primary_action_url,
        health=health,
        ownership=ownership,
        group_key=group_key,
        group_label=group_label,
        current_step=current_step or _STEP_BY_STATE[project.state],
        overview_summary=overview_summary,
        operator_state_label=project.state.value,
        technical_detail=technical_detail,
    )


def _agree_with_readiness(
    model: ProjectReadModel,
    readiness: ReadinessView | None,
) -> ProjectReadModel:
    """Let the gate run overrule a stored state that has outrun its evidence.

    `project.state` records how far the pipeline got. The readiness gates re-derive,
    from the artifacts on disk, whether that is still true — and the two can part
    company without either being corrupt. Approve an episode plan, let the script be
    written and verified, then change the plan: the state stays `SCRIPT_VERIFIED`,
    while `episode-plan-approval` goes blocked and voids everything downstream of it.

    Before this, the project row and the overview read that state and sent the reader
    to build audio, `/readiness` said four checks were stopped, and `/script` rendered
    an empty page. Four surfaces, four stories, one project.

    The rule is narrow on purpose. It fires only when the reader owns the next move
    and readiness names a destination the row does not — the case where the row would
    walk them past an unmet gate. When both name the same screen they already agree
    and nothing is rewritten, which is what happens on every healthy state; a failed
    run keeps its own account of itself, which is more specific than any gate's.
    """
    if readiness is None or readiness.action_url is None:
        return model
    if model.ownership != "you" or model.health == "danger":
        return model
    if readiness.action_url == model.primary_action_url:
        return model
    return replace(
        model,
        attention_label=readiness.headline,
        primary_action_label="بررسی آمادگی گفتار",
        primary_action_url=f"/projects/{model.project.project_id}/readiness",
        health="warning",
        overview_summary=readiness.explanation,
    )


def build_project_read_model(
    project: Project,
    *,
    failure_action_url: str | None = None,
    readiness: ReadinessView | None = None,
) -> ProjectReadModel:
    """One row's worth of truth about a project.

    Pass `readiness` wherever the caller already has (or can afford) a gate run; the
    model then reports what the evidence supports rather than what the state claims.
    """
    return _agree_with_readiness(
        _from_state(project, failure_action_url=failure_action_url),
        readiness,
    )


def _from_state(
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
            health="neutral",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
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
            health="neutral",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
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
            health="neutral",
            ownership="system",
            group_key="running",
            group_label="در حال انجام",
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
            health="neutral",
            ownership="system",
            group_key="running",
            group_label="در حال انجام",
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
            health="neutral",
            ownership="system",
            group_key="running",
            group_label="در حال انجام",
            overview_summary="کفایت منابع، اختلاف دیدگاه‌ها و مدت قابل‌پشتیبانی در حال سنجش است.",
        )

    if project.state == ProjectState.EPISODE_PLANNED:
        return _read_model(
            project,
            attention_label="ساختار گفتار را بررسی و تأیید کنید",
            primary_action_label="بررسی طرح گفتار",
            primary_action_url=f"/projects/{project_id}/episode",
            health="success",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
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
            health="neutral",
            ownership="system",
            group_key="running",
            group_label="در حال انجام",
            overview_summary="متن گفتار در حال نگارش، وارسی ساختاری و راستی‌آزمایی مستقل است.",
        )

    if project.state == ProjectState.SCRIPT_REVIEW_REQUIRED:
        return _read_model(
            project,
            attention_label="متن گفتار نیازمند بازبینی است",
            primary_action_label="ساخت صدا یا بازنویسی",
            primary_action_url=f"/projects/{project_id}/audio",
            health="warning",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
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
            health="success",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
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
            health="neutral",
            ownership="system",
            group_key="running",
            group_label="در حال انجام",
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
            health="danger",
            ownership="you",
            group_key="attention",
            group_label="منتظر شما",
            overview_summary=user_facing_error(project.last_error, action="generic"),
            technical_detail=project.last_error,
        )

    if project.state == ProjectState.COMPLETE:
        if project.delivery == DeliveryMode.TEXT:
            return _read_model(
                project,
                attention_label="گفتار آمادهٔ خواندن است",
                primary_action_label="خواندن گفتار",
                primary_action_url=f"/projects/{project_id}/lesson/1",
                health="success",
                ownership="none",
                group_key="complete",
                group_label="آمادهٔ خواندن",
                overview_summary="نسخهٔ نوشتاری و مسیر ردیابی شاهدها آماده‌اند.",
            )
        return _read_model(
            project,
            attention_label="گفتار آمادهٔ شنیدن است",
            primary_action_label="شنیدن گفتار",
            primary_action_url=f"/projects/{project_id}/audio",
            health="success",
            ownership="none",
            group_key="complete",
            group_label="آمادهٔ شنیدن",
            overview_summary="نسخهٔ شنیداری، متن همگام و مسیر ردیابی شاهدها آماده‌اند.",
        )

    return _read_model(
        project,
        attention_label="فرایند در حال انجام است",
        primary_action_label="مشاهدهٔ وضعیت",
        primary_action_url=f"/projects/{project_id}/processing",
        health="neutral",
        ownership="system",
        group_key="running",
        group_label="در حال انجام",
        overview_summary="گفتار از آخرین مرحلهٔ معتبر ادامه پیدا می‌کند.",
    )
