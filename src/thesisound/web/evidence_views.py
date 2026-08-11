"""Render-time helpers for claim → evidence display (Phase 1)."""

from __future__ import annotations

from uuid import UUID

from thesisound.domain import ClaimRecord, Locator, Project, Script, SupportStatus
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.source_manifest import UiSourceManifestStore

SUPPORT_KIND_LABELS: dict[str, str] = {
    "direct": "شاهد صریح",
    "inferential": "شاهد استنباطی",
}

SUPPORT_STATUS_LABELS: dict[str, str] = {
    SupportStatus.STRONG.value: "پشتوانه قوی",
    SupportStatus.MODERATE.value: "پشتوانه متوسط",
    SupportStatus.CONTESTED.value: "محل اختلاف",
    SupportStatus.UNCERTAIN.value: "نامطمئن",
}

_NO_PAGE_LOCATOR = "این منبع شماره‌گذاری صفحه ندارد؛ نشانی در سطح فصل است"

_SOURCE_REMOVED_MESSAGE = "این شاهد در دسترس نیست؛ منبع از مجموعه خارج شده است."
_UNAVAILABLE_MESSAGE = "این شاهد در دسترس نیست؛ پروندهٔ شاهد بارگذاری نشد."


def source_titles_for_project(
    project: Project,
    source_store: SourceArtifactStore,
) -> dict[UUID, str]:
    titles = {source.source_id: source.title for source in project.sources}
    for item in UiSourceManifestStore(
        source_store.workspace_root / str(project.project_id)
    ).load():
        titles.setdefault(item.source_id, item.title)
    return titles


def resolve_source_ids(
    project: Project,
    source_store: SourceArtifactStore,
) -> tuple[list[UUID], list[UUID]]:
    """Return (usable_source_ids, all_known_source_ids) for evidence/claim loading."""
    claim_ready = source_store.list_claim_ready_source_ids(project.project_id)
    if not project.sources:
        return list(claim_ready), list(claim_ready)

    usable = [source.source_id for source in project.sources if source.usable_as_evidence]
    known: list[UUID] = []
    seen: set[UUID] = set()
    for source_id in list(usable) + [s.source_id for s in project.sources] + list(claim_ready):
        if source_id not in seen:
            seen.add(source_id)
            known.append(source_id)
    return usable, known


def load_evidence_index(
    project: Project,
    source_store: SourceArtifactStore,
) -> dict[str, dict[str, object]]:
    """Map evidence_id → display row; usable sources are ok, others source_removed."""
    usable_ids, known_ids = resolve_source_ids(project, source_store)
    usable_set = set(usable_ids)
    titles = source_titles_for_project(project, source_store)
    evidence_by_id: dict[str, dict[str, object]] = {}

    for source_id in known_ids:
        try:
            items = source_store.load_evidence_items(project.project_id, source_id)
        except FileNotFoundError:
            continue
        status = "ok" if source_id in usable_set else "source_removed"
        for item in items:
            if item.evidence_id in evidence_by_id and evidence_by_id[item.evidence_id]["status"] == "ok":
                continue
            row: dict[str, object] = {
                "evidence_id": item.evidence_id,
                "status": status,
                "availability": status,
                "source_id": str(source_id),
                "source_title": titles.get(source_id, "منبع بدون عنوان"),
                "locator": locator_label(item.locator),
                "locator_label": locator_label(item.locator),
                "excerpt": item.supporting_excerpt,
                "support_kind": item.support_kind,
                "support_kind_label": SUPPORT_KIND_LABELS.get(
                    item.support_kind, item.support_kind
                ),
            }
            if status == "source_removed":
                row["message"] = _SOURCE_REMOVED_MESSAGE
            evidence_by_id[item.evidence_id] = row
    return evidence_by_id


def load_claim_index(
    project: Project,
    source_store: SourceArtifactStore,
) -> dict[str, ClaimRecord]:
    _, known_ids = resolve_source_ids(project, source_store)
    claims: dict[str, ClaimRecord] = {}
    for source_id in known_ids:
        try:
            ledger = source_store.load_claim_ledger(project.project_id, source_id)
        except FileNotFoundError:
            continue
        for claim in ledger.claims:
            claims.setdefault(claim.claim_id, claim)
    return claims


def locator_label(locator: Locator) -> str:
    parts: list[str] = []
    if locator.page_start is not None:
        page = str(locator.page_start)
        if locator.page_end is not None and locator.page_end != locator.page_start:
            page += f"–{locator.page_end}"
        parts.append(f"صفحه {page}")
    if locator.chapter:
        parts.append(f"فصل {locator.chapter}")
    if locator.section:
        parts.append(f"بخش {locator.section}")
    if locator.paragraph_start is not None:
        paragraph = str(locator.paragraph_start)
        if locator.paragraph_end is not None and locator.paragraph_end != locator.paragraph_start:
            paragraph += f"–{locator.paragraph_end}"
        parts.append(f"بند {paragraph}")
    if locator.page_start is None:
        parts.append(_NO_PAGE_LOCATOR)
    return "، ".join(parts)


def _evidence_row_for_id(
    evidence_id: str,
    evidence_by_id: dict[str, dict[str, object]],
) -> dict[str, object]:
    found = evidence_by_id.get(evidence_id)
    if found is not None:
        return found
    return {
        "evidence_id": evidence_id,
        "status": "unavailable",
        "availability": "unavailable",
        "source_id": None,
        "source_title": None,
        "locator": None,
        "locator_label": None,
        "excerpt": None,
        "support_kind": None,
        "support_kind_label": None,
        "message": _UNAVAILABLE_MESSAGE,
    }


def claim_groups_for_ids(
    claim_ids: list[str],
    *,
    turn_evidence_ids: list[str] | None,
    claims: dict[str, ClaimRecord],
    evidence_by_id: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Build claim_group[] for a turn or omitted-claim list."""
    turn_set = set(turn_evidence_ids) if turn_evidence_ids is not None else None
    groups: list[dict[str, object]] = []
    for claim_id in claim_ids:
        claim = claims.get(claim_id)
        if claim is None:
            groups.append(
                {
                    "claim_id": claim_id,
                    "claim_text": None,
                    "support_status": None,
                    "support_status_label": None,
                    "availability": "unavailable",
                    "evidence": [],
                }
            )
            continue
        if turn_set is None:
            evidence_ids = list(claim.evidence_ids)
        else:
            evidence_ids = [eid for eid in claim.evidence_ids if eid in turn_set]
        groups.append(
            {
                "claim_id": claim_id,
                "claim_text": claim.claim,
                "support_status": claim.support_status.value,
                "support_status_label": SUPPORT_STATUS_LABELS.get(
                    claim.support_status.value, claim.support_status.value
                ),
                "availability": "ok",
                "evidence": [
                    _evidence_row_for_id(evidence_id, evidence_by_id)
                    for evidence_id in evidence_ids
                ],
            }
        )
    return groups


def grounding_cue(
    claim_groups: list[dict[str, object]],
) -> dict[str, str] | None:
    for group in claim_groups:
        for item in group.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            if item.get("availability") != "ok" and item.get("status") != "ok":
                continue
            title = item.get("source_title")
            locator = item.get("locator_label") or item.get("locator")
            if title and locator:
                return {
                    "source_title": str(title),
                    "locator": str(locator),
                }
    return None


def segment_views(
    project: Project,
    script: Script | None,
    source_store: SourceArtifactStore,
) -> list[dict[str, object]]:
    if script is None or project.episode_plan is None:
        return []
    evidence_by_id = load_evidence_index(project, source_store)
    claims = load_claim_index(project, source_store)

    turns_by_segment: dict[str, list[dict[str, object]]] = {}
    for turn in script.turns:
        groups = claim_groups_for_ids(
            list(turn.claim_ids),
            turn_evidence_ids=list(turn.evidence_ids),
            claims=claims,
            evidence_by_id=evidence_by_id,
        )
        turns_by_segment.setdefault(turn.segment_id, []).append(
            {
                "turn": turn,
                "claim_groups": groups,
                "grounding_cue": grounding_cue(groups),
            }
        )
    return [
        {
            "segment": segment,
            "turns": turns_by_segment.get(segment.segment_id, []),
        }
        for segment in project.episode_plan.segments
    ]


def omitted_claim_views(
    omitted: list[object],
    *,
    claims: dict[str, ClaimRecord],
    evidence_by_id: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in omitted:
        claim_id = getattr(item, "claim_id", None) or (
            item.get("claim_id") if isinstance(item, dict) else None
        )
        reason = getattr(item, "reason", None) or (
            item.get("reason") if isinstance(item, dict) else None
        )
        if not claim_id:
            continue
        groups = claim_groups_for_ids(
            [str(claim_id)],
            turn_evidence_ids=None,
            claims=claims,
            evidence_by_id=evidence_by_id,
        )
        rows.append(
            {
                "claim_id": str(claim_id),
                "reason": str(reason or ""),
                "claim_groups": groups,
            }
        )
    return rows
