from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from thesisound.modeling import PromptBundle, PromptContract

_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptNotFoundError(FileNotFoundError):
    pass


class PromptContractError(ValueError):
    pass


class PromptRenderError(ValueError):
    pass


class PromptLoader:
    """Load immutable prompt contracts without embedding prompts in Python code."""

    def __init__(self, prompt_root: Path | None = None) -> None:
        self.prompt_root = prompt_root or self._discover_prompt_root()

    @staticmethod
    def _discover_prompt_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "prompts"
            if candidate.is_dir():
                return candidate
        raise PromptNotFoundError("Could not locate the prompts directory")

    def load(self, name: str) -> str:
        """Load a legacy single-file prompt for backwards compatibility."""

        normalized = name.removesuffix(".md")
        matches = sorted(self.prompt_root.glob(f"*_{normalized}.md"))
        if not matches:
            direct = self.prompt_root / f"{normalized}.md"
            if direct.exists():
                matches = [direct]
        if len(matches) != 1:
            raise PromptNotFoundError(
                f"Expected one prompt for {name!r}; found {len(matches)} in {self.prompt_root}"
            )
        return matches[0].read_text(encoding="utf-8")

    def load_bundle(
        self,
        name: str,
        variables: dict[str, Any],
        *,
        version: str | None = None,
    ) -> PromptBundle:
        version_dir = self._resolve_version_dir(name, version)
        contract_path = version_dir / "contract.json"
        try:
            raw_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract = PromptContract.model_validate(raw_contract)
        except FileNotFoundError as exc:
            raise PromptNotFoundError(f"Missing prompt contract: {contract_path}") from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PromptContractError(f"Invalid prompt contract: {contract_path}") from exc

        if contract.id != name:
            raise PromptContractError(
                f"Prompt directory {name!r} contains contract id {contract.id!r}."
            )
        if contract.version != version_dir.name:
            raise PromptContractError(
                f"Contract version {contract.version!r} does not match directory {version_dir.name!r}."
            )

        system_template = self._read_required(version_dir / contract.system_file)
        user_template = self._read_required(version_dir / contract.user_file)
        system_prompt = _render(system_template, variables)
        user_prompt = _render(user_template, variables)
        content_hash = _prompt_hash(contract, system_template, user_template)
        return PromptBundle(
            contract=contract,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            content_hash=content_hash,
        )

    def _resolve_version_dir(self, name: str, version: str | None) -> Path:
        prompt_dir = self.prompt_root / name
        if not prompt_dir.is_dir():
            raise PromptNotFoundError(f"Versioned prompt not found: {prompt_dir}")
        if version is not None:
            candidate = prompt_dir / version
            if not candidate.is_dir():
                raise PromptNotFoundError(f"Prompt version not found: {candidate}")
            return candidate

        candidates = [path for path in prompt_dir.iterdir() if path.is_dir()]
        if not candidates:
            raise PromptNotFoundError(f"No versions found for prompt {name!r}")
        return max(candidates, key=lambda path: _version_key(path.name))

    @staticmethod
    def _read_required(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptNotFoundError(f"Missing prompt template: {path}") from exc


def _render(template: str, variables: dict[str, Any]) -> str:
    required = set(_PLACEHOLDER.findall(template))
    missing = sorted(required - variables.keys())
    if missing:
        raise PromptRenderError(f"Missing prompt variables: {', '.join(missing)}")

    def replace(match: re.Match[str]) -> str:
        value = variables[match.group(1)]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    rendered = _PLACEHOLDER.sub(replace, template).strip()
    unresolved = _PLACEHOLDER.findall(rendered)
    if unresolved:
        raise PromptRenderError(f"Unresolved prompt variables: {', '.join(sorted(unresolved))}")
    return rendered


def _prompt_hash(
    contract: PromptContract,
    system_template: str,
    user_template: str,
) -> str:
    payload = {
        "contract": contract.model_dump(mode="json"),
        "system_template": system_template,
        "user_template": user_template,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    parts = re.split(r"[.-]", version)
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)
