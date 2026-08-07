from pathlib import Path


class PromptNotFoundError(FileNotFoundError):
    pass


class PromptLoader:
    """Load prompt contracts from the repository instead of embedding them in code."""

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
