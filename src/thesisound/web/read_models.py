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


_STATE_LABELS = {
    ProjectState.DRAFT: "پیش‌نویس",
    ProjectState.BRIEF_READY: "نیازمند تأیید برداشت",
    ProjectState.SOURCES_COLLECTING: "در حال افزودن منابع",
    ProjectState.SOURCE_SELECTION_REQUIRED: "نیازمند تأیید منابع",
    ProjectState.CORPUS_BUILDING: "در حال پردازش",
    ProjectState.CORPUS_READY: "مجموعه منابع آماده",
    ProjectState.EPISODE_PLANNING: "در حال ساخت طرح",
    ProjectState.EPISODE_PLANNED: "طرح آماده بازبینی",
    ProjectState.SCRIPT_DRAFTING: "در حال نوشتن متن",
    ProjectState.SCRIPT_READY: "متن آماده",
    ProjectState.SCRIPT_VERIFYING: "در حال راستی‌آزمایی",
    ProjectState.SCRIPT_VERIFIED: "متن تأییدشده",
    ProjectState.AUDIO_GENERATING: "در حال تولید صدا",
    ProjectState.AUDIO_READY: "صدا آماده بازبینی",
    ProjectState.AUDIO_VERIFYING: "در حال کنترل صدا",
    ProjectState.COMPLETE: "آماده شنیدن",
    ProjectState.FAILED_RETRYABLE: "نیازمند رفع خطا",
    ProjectState.FAILED_PERMANENT: "متوقف‌شده",
}


def build_project_read_model(project: Project) -> ProjectReadModel:
    project_id = str(project.project_id)
    if project.state in {ProjectState.DRAFT, ProjectState.BRIEF_READY}:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label="برداشت سیستم را بررسی کنید",
            primary_action_label="بررسی برداشت",
            primary_action_url=f"/projects/{project_id}/brief",
            tone="attention",
        )
    if project.state in {
        ProjectState.SOURCES_COLLECTING,
        ProjectState.SOURCE_SELECTION_REQUIRED,
    }:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label="منابع را اضافه یا تأیید کنید",
            primary_action_label="ادامه منابع",
            primary_action_url=f"/projects/{project_id}/sources",
            tone="attention",
        )
    if project.state == ProjectState.CORPUS_READY:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label="پوشش منابع را بررسی و طرح اپیزود را بسازید",
            primary_action_label="رفتن به طرح اپیزود",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="attention",
        )
    if project.state in {ProjectState.EPISODE_PLANNING, ProjectState.EPISODE_PLANNED}:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label=(
                "طرح اپیزود را بررسی کنید"
                if project.state == ProjectState.EPISODE_PLANNED
                else "وضعیت ارزیابی پوشش و ساخت طرح را ببینید"
            ),
            primary_action_label="مشاهده طرح اپیزود",
            primary_action_url=f"/projects/{project_id}/episode",
            tone="attention" if project.state == ProjectState.EPISODE_PLANNED else "running",
        )
    if project.state in {ProjectState.FAILED_RETRYABLE, ProjectState.FAILED_PERMANENT}:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label=project.last_error or "اجرای پروژه متوقف شده است",
            primary_action_label="مشاهده مشکل",
            primary_action_url=f"/projects/{project_id}/processing",
            tone="danger",
        )
    if project.state == ProjectState.COMPLETE:
        return ProjectReadModel(
            project=project,
            state_label=_STATE_LABELS[project.state],
            attention_label="اپیزود آماده است",
            primary_action_label="گوش دادن",
            primary_action_url=f"/projects/{project_id}/listen",
            tone="success",
        )
    return ProjectReadModel(
        project=project,
        state_label=_STATE_LABELS[project.state],
        attention_label="فرایند در حال انجام است",
        primary_action_label="مشاهده وضعیت",
        primary_action_url=f"/projects/{project_id}/processing",
        tone="running",
    )
