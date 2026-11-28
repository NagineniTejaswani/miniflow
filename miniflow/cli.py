import typer

from .parser import WorkflowError, load_workflow
from .docker_executor import DockerJobExecutor
from .scheduler import Scheduler
from .timeline import format_timeline
app = typer.Typer(help="MiniFlow: a tiny durable workflow engine.")
from pathlib import Path

@app.callback()
def main() -> None:
    """MiniFlow CLI."""


@app.command()
def validate(path: str) -> None:
    """Validate a workflow definition."""
    try:
        workflow = load_workflow(path)
    except WorkflowError as e:
        typer.secho(f"✗ Invalid: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(
        f"✓ Valid: '{workflow.name}' ({len(workflow.jobs)} jobs)",
        fg=typer.colors.GREEN,
    )

@app.command()
def run(
    path: str,
    max_concurrency: int = typer.Option(
        4, "--max-concurrency", "-j", min=1, help="Max jobs running at once"),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Folder shared with every job at /workspace")
) -> None:
    """Execute a workflow in Docker containers."""
    try:
        workflow = load_workflow(path)
    except WorkflowError as e:
        typer.secho(f"✗ Invalid: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if workspace and not Path(workspace).is_dir():
        typer.secho(f"✗ Workspace folder not found: {workspace}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    scheduler = Scheduler.from_workflow(workflow, max_concurrency=max_concurrency)
    scheduler.run(DockerJobExecutor(workspace=workspace))

    typer.echo(f"Workflow: {workflow.name}  (max concurrency {max_concurrency})\n")
    for name in workflow.jobs:
        state = scheduler.state[name].value
        result = scheduler.results.get(name)
        line = f"{name:<12} {state}"
        if result and not result.success:
            line += f"  ({result.message})"
        typer.echo(line)
        if result and result.stdout.strip():
            typer.echo(f"    stdout: {result.stdout.strip()}")
        if result and result.stderr.strip():
            typer.echo(f"    stderr: {result.stderr.strip()}")

    typer.echo("\nTimeline:")
    typer.echo(format_timeline(scheduler.timeline))

    if any(s.value == "FAILED" for s in scheduler.state.values()):
        raise typer.Exit(code=1)