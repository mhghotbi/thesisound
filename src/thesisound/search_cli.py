from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.adapters.search.gemini import GeminiWebSearchPort
from thesisound.config import Settings
from thesisound.domain import SearchQuery, SourceRole
from thesisound.services.runtime_preflight import RuntimePreflight


def register_search_commands(app: typer.Typer) -> None:
    @app.command("search-web")
    def search_web(
        query: str = typer.Argument(..., help="Search query"),
        purpose: str = typer.Option(
            "Find credible candidate sources for a grounded podcast.",
            help="Why these sources are needed",
        ),
        language: str = typer.Option("fa", help="Preferred source language"),
        limit: int = typer.Option(10, min=1, max=20),
    ) -> None:
        """Search the web through Gemini grounding and show candidate sources."""

        settings = Settings()
        RuntimePreflight(settings).require("model")
        model_port = GeminiStructuredModel(api_keys=settings.gemini_api_keys)
        search = GeminiWebSearchPort(model_port, model=settings.model_fast)
        results = search.search(
            SearchQuery(
                query=query,
                provider="web",
                source_role=SourceRole.REFERENCE,
                language=language,
                purpose=purpose,
                priority=3,
            )
        )

        table = Table(title="Gemini Google Search candidates")
        table.add_column("عنوان")
        table.add_column("URL")
        table.add_column("وضعیت")
        for result in results[:limit]:
            table.add_row(
                result.title,
                result.url or "—",
                "candidate only; not evidence",
            )
        console = Console()
        console.print(table)
        if not results:
            console.print("[yellow]No grounded source URLs were returned.[/yellow]")
