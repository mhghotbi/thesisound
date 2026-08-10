from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.services.eval_harness import (
    dry_run,
    report_markdown,
    report_payload,
    run_eval,
)


def register_eval_command(app: typer.Typer) -> None:
    @app.command("eval")
    def evaluate(
        case_ids: Annotated[
            list[str] | None, typer.Option("--case", help="Run only this case ID; repeatable")
        ] = None,
        dry: Annotated[
            bool,
            typer.Option("--dry-run", help="Validate cases without constructing a model client"),
        ] = False,
        report: Annotated[Path | None, typer.Option(help="JSON report output path")] = None,
        workspace_root: Annotated[
            Path | None, typer.Option(help="Isolated evaluation workspace root")
        ] = None,
        as_json: Annotated[
            bool, typer.Option("--json", help="Print JSON instead of a table")
        ] = False,
    ) -> None:
        """Run the frozen machine-checkable golden set; live runs write and spend."""

        settings = Settings()
        eval_root = Path("benchmarks/eval").resolve()
        try:
            if dry:
                payload = dry_run(eval_root, case_ids)
                if as_json:
                    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    console = Console()
                    table = Table(title="Golden evaluation dry run")
                    table.add_column("Case")
                    table.add_column("Sources")
                    table.add_column("Sequence")
                    for case in payload["cases"]:
                        table.add_row(
                            case["case_id"],
                            str(len(case["sources"])),
                            " → ".join(case["sequence"]),
                        )
                    console.print(table)
                    console.print(f"Gates: {payload['gates']}")
                return

            runtime = (workspace_root or eval_root / "runtime").expanduser().resolve()
            result = run_eval(
                eval_root=eval_root,
                workspace_root=runtime,
                case_ids=case_ids,
                settings=settings,
            )
            payload = report_payload(result)
            output = (
                report or eval_root / "reports" / f"{datetime.now(UTC).date().isoformat()}.json"
            )
            output = output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            markdown = output.with_suffix(".md")
            markdown.write_text(report_markdown(result), encoding="utf-8")
            if as_json:
                typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                table = Table(title="Golden evaluation release gates")
                table.add_column("Gate")
                table.add_column("Status")
                table.add_column("Observed")
                table.add_column("Threshold")
                for gate in result.gates:
                    table.add_row(
                        gate.name,
                        gate.status,
                        str(gate.observed if gate.observed is not None else "unknown"),
                        f"{gate.comparison} {gate.threshold}",
                    )
                Console().print(table)
                Console().print(f"Reports: {output} · {markdown}")
            if result.exit_code:
                raise typer.Exit(code=result.exit_code)
        except typer.Exit:
            raise
        except (OSError, ValueError) as exc:
            # stderr is a Console constructor argument, not a print keyword: passing
            # it to print raises TypeError and hides the error it was reporting.
            Console(stderr=True).print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
