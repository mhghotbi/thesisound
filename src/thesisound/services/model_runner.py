from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound.model_routing import ResolvedModelRoute
from thesisound.modeling import (
    DeterministicValidationError,
    GroundingMode,
    ModelAttemptRecord,
    ModelError,
    ModelExecution,
    ModelProviderError,
    ModelRunRecord,
)
from thesisound.ports import RunMetadata, TextModelPort
from thesisound.prompt_loader import PromptLoader
from thesisound.services.model_retry import decide_retry
from thesisound.services.model_run_store import WorkspaceModelRunStore

type Validator[T: BaseModel] = Callable[[T], None]

_GROUNDING_POLICY_BY_STAGE: dict[str, GroundingMode] = {
    "research_brief": "google_search_and_url_context",
    "query_planner": "google_search",
    "source_discovery": "google_search_and_url_context",
    "source_triage": "url_context",
    # Glossary is source-bound terminology from supplied packs; keep ungrounded
    # so it can run on Okian during script drafting.
}
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


class ModelRunner:
    """Execute one versioned prompt contract and persist an auditable run."""

    def __init__(
        self,
        model_port: TextModelPort,
        prompt_loader: PromptLoader,
        run_store: WorkspaceModelRunStore,
        *,
        base_retry_delay_seconds: float = 1,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_port = model_port
        self.prompt_loader = prompt_loader
        self.run_store = run_store
        self.base_retry_delay_seconds = base_retry_delay_seconds
        self.sleeper = sleeper

    def run[T: BaseModel](
        self,
        *,
        project_id: UUID,
        stage: str,
        prompt_name: str,
        variables: dict[str, Any],
        output_type: type[T],
        model: str,
        prompt_version: str | None = None,
        validator: Validator[T] | None = None,
        grounding_mode: GroundingMode | None = None,
        grounding_urls: list[str] | None = None,
    ) -> ModelExecution[T]:
        bundle = self.prompt_loader.load_bundle(
            prompt_name,
            variables,
            version=prompt_version,
        )
        if bundle.contract.output_model != output_type.__name__:
            raise ValueError(
                f"Prompt expects {bundle.contract.output_model}, not {output_type.__name__}."
            )

        # Route keys in model-routing.toml match prompt contracts (e.g.
        # persian_script_segment), not always the observability stage string
        # (e.g. script_segment:{id} or document_map_part).
        route = _resolve_model_route(
            self.model_port,
            stage=bundle.contract.id,
            requested_model=model,
            model_tier=bundle.contract.model_tier,
        )
        resolved_urls = _resolve_grounding_urls(variables, grounding_urls)
        resolved_mode = _resolve_grounding_mode(
            stage,
            grounding_mode,
            has_urls=bool(resolved_urls),
        )
        input_hash = _hash_variables(
            {
                "variables": variables,
                "grounding_mode": resolved_mode,
                "grounding_urls": resolved_urls,
                "provider": route.provider,
                "model": route.model,
                "model_profile": route.profile,
            }
        )
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=bundle.contract.id,
            prompt_version=bundle.contract.version,
            prompt_hash=bundle.content_hash,
            input_hash=input_hash,
            provider=route.provider,
            model=route.model,
            output_model=output_type.__name__,
            grounding_mode=resolved_mode,
            grounding_urls=resolved_urls,
        )
        self.run_store.initialize(
            record,
            bundle,
            model=route.model,
            variable_names=list(variables),
        )

        user_prompt = bundle.user_prompt
        ledger = getattr(self.model_port, "observability", None)
        for attempt_number in range(1, bundle.contract.max_attempts + 1):
            started = perf_counter()
            metadata = RunMetadata(
                stage=stage,
                prompt_version=bundle.contract.version,
                model_or_provider=route.model,
                provider=route.provider,
                model_profile=route.profile,
                attempt=attempt_number,
                input_artifact_hashes=[input_hash],
                grounding_mode=resolved_mode,
                grounding_urls=resolved_urls,
                trace_id=record.run_id,
                project_id=project_id,
                operation=_operation_for_grounding(resolved_mode),
                prompt_id=bundle.contract.id,
                subject_type="model_stage",
                subject_id=stage,
                max_provider_attempts=1,
            )
            response = None
            try:
                response = self.model_port.generate_structured(
                    system_prompt=bundle.system_prompt,
                    user_prompt=user_prompt,
                    output_type=output_type,
                    model=route.model,
                    metadata=metadata,
                )
                if validator is not None:
                    try:
                        validator(response.output)
                    except DeterministicValidationError:
                        raise
                    except ValueError as exc:
                        raise DeterministicValidationError(str(exc)) from exc

                record.grounding_source_count = len(response.grounding.sources)
                record.web_search_queries = response.grounding.web_search_queries
                record.attempts.append(
                    ModelAttemptRecord(
                        attempt=attempt_number,
                        latency_ms=response.latency_ms,
                        success=True,
                        usage=response.usage,
                        finish_reason=response.finish_reason,
                        grounding_source_count=len(response.grounding.sources),
                        web_search_queries=response.grounding.web_search_queries,
                        call_id=response.call_id,
                    )
                )
                record.status = "succeeded"
                record.completed_at = datetime.now(UTC)
                self.run_store.save_output(record, response.output)
                self.run_store.save_grounding(record, response.grounding)
                self.run_store.save_record(record)
                return ModelExecution[T](output=response.output, record=record)
            except ModelError as exc:
                latency_ms = max(0, round((perf_counter() - started) * 1000))
                decision = decide_retry(
                    exc,
                    attempt=attempt_number,
                    max_attempts=bundle.contract.max_attempts,
                    retry_schema_errors=bundle.contract.retry_schema_errors,
                    base_delay_seconds=self.base_retry_delay_seconds,
                )
                call_id = response.call_id if response is not None else metadata.call_id
                if response is not None and ledger is not None:
                    ledger.reject(call_id, exc)
                if decision.should_retry and ledger is not None:
                    ledger.record_retry(
                        call_id,
                        reason=type(exc).__name__,
                        backoff_ms=round(decision.delay_seconds * 1000),
                    )
                record.attempts.append(
                    ModelAttemptRecord(
                        attempt=attempt_number,
                        latency_ms=latency_ms,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        retryable=decision.should_retry,
                        retry_delay_ms=round(decision.delay_seconds * 1000),
                        call_id=call_id,
                    )
                )
                self.run_store.save_record(record)
                if not decision.should_retry:
                    record.status = "failed"
                    record.completed_at = datetime.now(UTC)
                    record.error_type = type(exc).__name__
                    record.error_message = str(exc)
                    self.run_store.save_error(record)
                    self.run_store.save_record(record)
                    raise
                if decision.delay_seconds:
                    self.sleeper(decision.delay_seconds)
                if decision.repair_instruction:
                    user_prompt = _append_repair_instruction(
                        bundle.user_prompt,
                        decision.repair_instruction,
                    )
            except Exception as exc:
                wrapped = ModelProviderError(str(exc), retryable=False)
                if ledger is not None:
                    ledger.fail(metadata.call_id, wrapped)
                record.attempts.append(
                    ModelAttemptRecord(
                        attempt=attempt_number,
                        latency_ms=max(0, round((perf_counter() - started) * 1000)),
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        retryable=False,
                        call_id=metadata.call_id,
                    )
                )
                record.status = "failed"
                record.completed_at = datetime.now(UTC)
                record.error_type = type(exc).__name__
                record.error_message = str(exc)
                self.run_store.save_error(record)
                self.run_store.save_record(record)
                raise wrapped from exc

        raise AssertionError("Model runner exhausted attempts without returning or raising.")


def _resolve_model_route(
    model_port: TextModelPort,
    *,
    stage: str,
    requested_model: str,
    model_tier: str,
) -> ResolvedModelRoute:
    resolver = getattr(model_port, "resolve_route", None)
    if callable(resolver):
        return resolver(
            stage=stage,
            requested_model=requested_model,
            model_tier=model_tier,
        )
    return ResolvedModelRoute(
        provider=model_port.provider,
        model=requested_model,
    )


def grounding_policy_for_stage(stage: str) -> GroundingMode:
    return _GROUNDING_POLICY_BY_STAGE.get(stage, "none")


def _resolve_grounding_mode(
    stage: str,
    requested: GroundingMode | None,
    *,
    has_urls: bool,
) -> GroundingMode:
    mode = requested or grounding_policy_for_stage(stage)
    if mode == "url_context" and not has_urls:
        return "none"
    if mode == "google_search_and_url_context" and not has_urls:
        return "google_search"
    return mode


def _resolve_grounding_urls(
    variables: dict[str, Any],
    supplied: list[str] | None,
) -> list[str]:
    urls = list(supplied or [])
    urls.extend(_URL_PATTERN.findall(json.dumps(variables, ensure_ascii=False, default=str)))
    cleaned = [url.rstrip(".,);]}") for url in urls]
    return list(dict.fromkeys(cleaned))[:20]


def _hash_variables(variables: dict[str, Any]) -> str:
    canonical = json.dumps(
        variables,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_repair_instruction(user_prompt: str, instruction: str) -> str:
    return (
        f"{user_prompt}\n\n<REPAIR_INSTRUCTION>\n"
        f"{instruction}\n"
        "Return only a corrected response matching the supplied schema.\n"
        "</REPAIR_INSTRUCTION>"
    )


def _operation_for_grounding(mode: GroundingMode) -> str:
    if mode in {"google_search", "google_search_and_url_context"}:
        return "google_search"
    if mode == "url_context":
        return "url_context"
    return "structured_text"
