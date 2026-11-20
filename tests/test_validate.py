import textwrap

import pytest
from typer.testing import CliRunner

from miniflow.cli import app
from miniflow.parser import WorkflowError, load_workflow
from miniflow.scheduler import find_cycle_jobs


def write(tmp_path, text):
    p = tmp_path / "wf.yaml"
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_valid_workflow_loads():
    wf = load_workflow("workflows/parallel.yaml")
    assert wf.name == "example-pipeline"
    assert len(wf.jobs) == 4


def test_missing_image_rejected(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            command: ["echo", "hi"]
    """)
    with pytest.raises(WorkflowError, match="image"):
        load_workflow(p)


def test_command_must_be_list(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            image: alpine
            command: "echo hi"
    """)
    with pytest.raises(WorkflowError, match="command"):
        load_workflow(p)


def test_empty_command_rejected(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            image: alpine
            command: []
    """)
    with pytest.raises(WorkflowError):
        load_workflow(p)


def test_unknown_field_rejected(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            image: alpine
            command: ["echo"]
            imagee: typo
    """)
    with pytest.raises(WorkflowError):
        load_workflow(p)


def test_unknown_dependency(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            needs: [ghost]
            image: alpine
            command: ["echo"]
    """)
    with pytest.raises(WorkflowError, match="unknown job 'ghost'"):
        load_workflow(p)


def test_self_dependency(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            needs: [a]
            image: alpine
            command: ["echo"]
    """)
    with pytest.raises(WorkflowError, match="itself"):
        load_workflow(p)


def test_duplicate_job_key(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            image: alpine
            command: ["echo", "1"]
          a:
            image: alpine
            command: ["echo", "2"]
    """)
    with pytest.raises(WorkflowError, match="Duplicate key 'a'"):
        load_workflow(p)


def test_two_job_cycle(tmp_path):
    p = write(tmp_path, """
        name: x
        jobs:
          a:
            needs: [b]
            image: alpine
            command: ["echo"]
          b:
            needs: [a]
            image: alpine
            command: ["echo"]
    """)
    with pytest.raises(WorkflowError, match="Cycle"):
        load_workflow(p)


def test_cycle_algorithm_directly():
    assert find_cycle_jobs({"a": [], "b": ["a"], "c": ["b"]}) == []
    assert sorted(find_cycle_jobs({"a": ["c"], "b": ["a"], "c": ["b"]})) == ["a", "b", "c"]


def test_cli_exit_codes(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(app, ["validate", "workflows/parallel.yaml"])
    assert ok.exit_code == 0

    bad = write(tmp_path, "name: x\njobs: {}\n")
    res = runner.invoke(app, ["validate", bad])
    assert res.exit_code == 1