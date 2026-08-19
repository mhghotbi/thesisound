"""Deterministic glossary harvest: always run; model only when open decisions remain."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from thesisound.concepts import ConceptCell
from thesisound.domain import ClaimRecord, ClaimType, ExtractedDefinition, GlossaryTerm
from thesisound.episode import SegmentEvidencePack
from thesisound.modeling import ModelRunRecord
from thesisound.script import Glossary

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_ARABIC = re.compile(r"[\u0600-\u06ff]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_MIN_LATIN_TOKEN_LEN = 2

GLOSSARY_MODEL_SKIP_PREFIX = "Glossary model skipped: no open translation decisions"


@dataclass(frozen=True)
class DeterministicGlossaryResult:
    glossary: Glossary
    needs_model: bool
    corpus_has_latin_tokens: bool
    warnings: list[str] = field(default_factory=list)
    run_record: ModelRunRecord | None = None


def has_persian_letters(text: str) -> bool:
    return bool(_ARABIC.search(text))


def has_latin_letters(text: str) -> bool:
    return bool(_LATIN_LETTER.search(text))


def is_confident_persian_form(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return has_persian_letters(stripped)


def extract_latin_tokens(text: str) -> list[str]:
    """Return distinct Latin-script word tokens from text (order preserved)."""

    seen: set[str] = set()
    out: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if len(token) < _MIN_LATIN_TOKEN_LEN:
            continue
        letters = [char for char in token if char.isalpha()]
        if not letters:
            continue
        latin = sum("a" <= char.lower() <= "z" for char in letters)
        if latin / len(letters) < 0.75:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def text_has_latin_tokens(text: str) -> bool:
    return bool(extract_latin_tokens(text))


def _preferred_from_definition_pair(term: str, definition: str) -> str | None:
    """Pick a confident Persian preferred form from a term/definition pair."""

    if is_confident_persian_form(term):
        return term.strip()
    # Definition body often glosses a Latin term in Persian; take the first
    # Arabic-script token as a weak but deterministic preferred form.
    if is_confident_persian_form(definition):
        persian_tokens = [
            match.group(0)
            for match in _TOKEN.finditer(definition)
            if has_persian_letters(match.group(0))
        ]
        if persian_tokens:
            # First Persian token is usually the gloss; longest often picks a
            # later descriptive word (e.g. فعالیت over زحمت).
            return persian_tokens[0]
        return definition.strip()
    return None


def _preferred_from_definition(definition: ExtractedDefinition) -> str | None:
    return _preferred_from_definition_pair(definition.term, definition.definition)


def _term_from_preferred(source_term: str, preferred: str) -> GlossaryTerm:
    return GlossaryTerm(
        source_term=source_term.strip(),
        preferred_persian=preferred,
        first_use_form=preferred,
        subsequent_use_form=preferred,
        pronunciation_hint=None,
        translation_status="standard",
    )


def empty_glossary_run_record(project_id: UUID, model: str) -> ModelRunRecord:
    """Synthetic run record for a deterministic (no-model) glossary build."""

    record = ModelRunRecord(
        project_id=project_id,
        stage="glossary",
        prompt_id="glossary",
        prompt_version="not-run",
        prompt_hash="",
        input_hash="",
        provider="none",
        model=model,
        output_model="GlossaryDraft",
        status="succeeded",
    )
    record.completed_at = record.started_at
    return record


def build_deterministic_glossary(
    *,
    project_id: UUID,
    definitions: list[ExtractedDefinition],
    evidence_packs: list[SegmentEvidencePack],
    claims: list[ClaimRecord],
    concept_cells: Sequence[ConceptCell] = (),
    model: str = "deterministic",
) -> DeterministicGlossaryResult:
    """Harvest glossary terms without a model call.

    Promotes only terms with a confident Persian preferred form. Any Latin
    candidate without such a form, any pronunciation-risk Latin remnant, or
    conflicting preferred forms across sources sets ``needs_model``. C6 also
    calls the model when any concept cell has a ``label_source`` or at least
    five definition claims exist.
    """

    # source_term.casefold() -> list of (preferred, source_id) for conflict detect
    preferred_by_term: dict[str, list[tuple[str, UUID | None]]] = defaultdict(list)
    unresolved_latin: set[str] = set()
    corpus_has_latin = False
    display_term: dict[str, str] = {}

    for definition in definitions:
        source = definition.term.strip()
        if not source:
            continue
        key = source.casefold()
        display_term.setdefault(key, source)
        preferred = _preferred_from_definition(definition)
        if preferred is not None:
            preferred_by_term[key].append((preferred, definition.source_id))
        elif has_latin_letters(source) or text_has_latin_tokens(source):
            corpus_has_latin = True
            unresolved_latin.add(key)
        if has_latin_letters(source) or text_has_latin_tokens(definition.definition):
            corpus_has_latin = True

    for pack in evidence_packs:
        for item in pack.evidence_items:
            for token in extract_latin_tokens(item.supporting_excerpt):
                corpus_has_latin = True
                key = token.casefold()
                display_term.setdefault(key, token)
                if key not in preferred_by_term:
                    unresolved_latin.add(key)
            for token in extract_latin_tokens(item.claim):
                corpus_has_latin = True
                key = token.casefold()
                display_term.setdefault(key, token)
                if key not in preferred_by_term:
                    unresolved_latin.add(key)

    definition_claim_count = 0
    for claim in claims:
        for token in extract_latin_tokens(claim.claim):
            corpus_has_latin = True
            key = token.casefold()
            display_term.setdefault(key, token)
            if key not in preferred_by_term:
                unresolved_latin.add(key)
        if claim.claim_type != ClaimType.DEFINITION:
            continue
        definition_claim_count += 1
        source = (claim.term or "").strip() or claim.claim.strip()
        if not source:
            continue
        key = source.casefold()
        display_term.setdefault(key, source)
        preferred = _preferred_from_definition_pair(source, claim.claim)
        if preferred is not None:
            preferred_by_term[key].append((preferred, None))
        elif has_latin_letters(source) or text_has_latin_tokens(source):
            corpus_has_latin = True
            unresolved_latin.add(key)
        if has_latin_letters(source) or text_has_latin_tokens(claim.claim):
            corpus_has_latin = True

    cells_with_source_label = False
    for cell in concept_cells:
        label_source = (cell.label_source or "").strip()
        if not label_source:
            continue
        cells_with_source_label = True
        key = label_source.casefold()
        display_term.setdefault(key, label_source)
        preferred = cell.label_fa.strip()
        if preferred:
            preferred_by_term[key].append((preferred, None))
        if has_latin_letters(label_source) or has_latin_letters(preferred):
            corpus_has_latin = True

    conflicting_keys: set[str] = set()
    confident_terms: list[GlossaryTerm] = []
    for key, entries in preferred_by_term.items():
        distinct = {preferred for preferred, _ in entries}
        if len(distinct) >= 2:
            conflicting_keys.add(key)
            continue
        preferred = next(iter(distinct))
        source = display_term.get(key, key)
        if not is_confident_persian_form(preferred):
            if has_latin_letters(source):
                unresolved_latin.add(key)
            continue
        # Latin source with a confident Persian preferred is promotable without
        # a model call (acceptance: non-empty deterministic glossary on Latin corpus).
        # Pronunciation hints remain a model concern only when no Persian form exists.
        confident_terms.append(_term_from_preferred(source, preferred))
        unresolved_latin.discard(key)

    # Deduplicate by source_term casefold, prefer first.
    seen_keys: set[str] = set()
    unique_terms: list[GlossaryTerm] = []
    for term in confident_terms:
        key = term.source_term.casefold()
        if key in seen_keys or key in conflicting_keys:
            continue
        seen_keys.add(key)
        unique_terms.append(term)

    # Open decisions: unresolved Latin / conflicts, plus C6 concept-map seeds.
    needs_model = bool(
        unresolved_latin
        or conflicting_keys
        or cells_with_source_label
        or definition_claim_count >= 5
    )

    warnings: list[str] = []
    if conflicting_keys:
        sample = ", ".join(sorted(conflicting_keys)[:4])
        warnings.append(f"Conflicting glossary forms for: {sample}.")
    if unresolved_latin:
        sample = ", ".join(sorted(unresolved_latin)[:4])
        warnings.append(f"Terms lacking confident Persian form: {sample}.")

    run = empty_glossary_run_record(project_id, model)
    if not needs_model:
        warnings.append(
            f"{GLOSSARY_MODEL_SKIP_PREFIX} ({len(unique_terms)} terms)."
        )

    glossary = Glossary(
        project_id=project_id,
        terms=unique_terms,
        warnings=list(warnings),
        model_run_id=run.run_id,
        build_kind="deterministic",
        corpus_had_latin_tokens=corpus_has_latin,
    )
    return DeterministicGlossaryResult(
        glossary=glossary,
        needs_model=needs_model,
        corpus_has_latin_tokens=corpus_has_latin,
        warnings=list(warnings),
        run_record=run,
    )
