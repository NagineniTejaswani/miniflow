import typer

from .parser import WorkflowError, load_workflow

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