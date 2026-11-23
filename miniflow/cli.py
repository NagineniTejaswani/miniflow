import typer

from .parser import WorkflowError, load_workflow
from .docker_executor import DockerJobExecutor
from .scheduler import Scheduler

app = typer.Typer(help="MiniFlow: a tiny durable workflow engine.")


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
def run(path: str) -> None:
    """Execute a workflow in Docker containers."""
    try:
        workflow = load_workflow(path)
    except WorkflowError as e:
        typer.secho(f"✗ Invalid: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    scheduler = Scheduler.from_workflow(workflow)
    scheduler.run(DockerJobExecutor())

    typer.echo(f"Workflow: {workflow.name}\n")
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

    if any(s.value == "FAILED" for s in scheduler.state.values()):
        raise typer.Exit(code=1)