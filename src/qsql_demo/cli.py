"""The ``qsql`` command-line interface."""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .compiler import Project
from .errors import QsqlError
from .overrides import collect
from .scaffold import write_scaffold

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="A notebook-like CLI for SQL: named cells with comment-driven, pluggable config.",
)
console = Console()

DEFAULT_FILE = "base.sql"

_FileArg = typer.Argument(DEFAULT_FILE, help="Path to the .qsql/.sql file.")
_SelectOpt = typer.Option(None, "--select", "-l", help="Cell selection: name, +upstream, downstream+.")
_SetOpt = typer.Option(None, "--set", "-s", help="Override config: key.path=value (repeatable).")


def _init(name: str) -> None:
    try:
        write_scaffold(name)
    except FileExistsError:
        console.print(f"[yellow]{name} already exists; not overwriting.[/]")
        raise typer.Exit(1)
    console.print(f"[green]created {name}[/] — run it with [bold]qsql run[/].")


def _load(file: str, set_pairs: Optional[list[str]] = None) -> Project:
    try:
        overrides = collect(set_pairs, os.environ)
        return Project.from_file(file, overrides=overrides)
    except FileNotFoundError:
        console.print(f"[red]error:[/] file not found: {file}")
        raise typer.Exit(1)
    except QsqlError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Run with no command to scaffold a starter base.sql."""
    if ctx.invoked_subcommand is None:
        _init(DEFAULT_FILE)


@app.command()
def init(name: str = typer.Argument(DEFAULT_FILE, help="File to create.")) -> None:
    """Scaffold a starter .qsql file (won't overwrite an existing one)."""
    _init(name)


@app.command("list")
def list_cells(file: str = _FileArg) -> None:
    """List cells with engine, sink, autorun, and dependencies."""
    project = _load(file)
    table = Table(title=file)
    for column in ("cell", "engine", "sink", "autorun", "depends on"):
        table.add_column(column)
    for name in project.order():
        cell = project.cell(name)
        table.add_row(
            name,
            cell.engine,
            cell.sink,
            "✓" if getattr(cell.config, "autorun", True) else "✗",
            ", ".join(sorted(project.deps.get(name, set()))) or "—",
        )
    console.print(table)
    console.print("order: " + " → ".join(project.order()))


@app.command()
def show(cell: str, file: str = _FileArg) -> None:
    """Print a cell's rendered SQL."""
    project = _load(file)
    try:
        rendered = project.cell(cell)
    except KeyError:
        console.print(f"[red]error:[/] no such cell: {cell}")
        raise typer.Exit(1)
    console.print(f"[bold]{cell}[/] ({rendered.engine} → {rendered.sink})")
    console.print(rendered.sql)


@app.command()
def compile(file: str = _FileArg, select: Optional[list[str]] = _SelectOpt) -> None:
    """Print the rendered SQL for the selected cells."""
    project = _load(file)
    for name in project.select(select):
        console.rule(name)
        console.print(project.cell(name).sql)


@app.command()
def run(
    file: str = _FileArg,
    select: Optional[list[str]] = _SelectOpt,
    set_: Optional[list[str]] = _SetOpt,
) -> None:
    """Compile and run the pipeline, landing each cell's output."""
    project = _load(file, set_)
    results = project.run(select=select)

    table = Table(title=f"qsql run · {file}")
    for column in ("cell", "status", "rows", "elapsed", "target"):
        table.add_column(column)
    for result in results:
        status = "[green]ok[/]" if result.ok else "[red]error[/]"
        elapsed = f"{result.elapsed:.3f}s" if result.elapsed is not None else ""
        detail = result.target if result.ok else (result.error or "")
        table.add_row(result.name, status, str(result.rows or ""), elapsed, detail)
    console.print(table)

    if any(not r.ok for r in results):
        raise typer.Exit(1)


@app.command()
def watch(file: str = _FileArg, set_: Optional[list[str]] = _SetOpt) -> None:
    """Watch the file and re-run changed cells (and their downstream) on save."""
    from .watcher import watch_file

    overrides = collect(set_, os.environ)

    def on_event(kind: str, names: list[str], payload: object) -> None:
        if kind == "error":
            console.print(f"[red]compile error:[/] {payload}")
        elif not names:
            console.print("[dim]no autorun cells to rebuild[/]")
        else:
            failed = [r.name for r in payload if not r.ok] if isinstance(payload, list) else []
            mark = "[red]" if failed else "[green]"
            console.print(f"{mark}ran[/] {', '.join(names)}" + (f"  (failed: {', '.join(failed)})" if failed else ""))

    # surface an initial compile error cleanly
    _load(file, set_)
    console.print(f"[bold]watching {file}[/] — edit and save to rebuild (ctrl-c to stop)")
    try:
        watch_file(file, overrides=overrides, on_event=on_event)
    except KeyboardInterrupt:
        console.print("stopped")


@app.command()
def tui(file: str = _FileArg, set_: Optional[list[str]] = _SetOpt) -> None:
    """Launch the interactive TUI (master-detail, VisiData-style data sheet)."""
    from .tui import QsqlApp

    project = _load(file, set_)
    QsqlApp(project, file=file, overrides=collect(set_, os.environ)).run()


if __name__ == "__main__":  # pragma: no cover
    app()
