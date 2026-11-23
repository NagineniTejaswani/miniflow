import docker
import pytest
from docker.errors import DockerException
from pydantic import ValidationError
from typer.testing import CliRunner

from miniflow.cli import app
from miniflow.docker_executor import (
    ContainerResult, DockerJobExecutor, ImageNotApproved,
)
from miniflow.executor import FailureKind, FakeExecutor, JobResult
from miniflow.models import Job, JobState
from miniflow.parser import load_workflow
from miniflow.scheduler import Scheduler


def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


needs_docker = pytest.mark.skipif(not docker_available(), reason="Docker not running")


class StubDocker:
    """Stands in for DockerExecutor so these tests need no Docker."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def run(self, image, command, timeout=60, mem_limit="128m"):
        self.calls.append((image, command, timeout))
        if self.error:
            raise self.error
        return self.result


def container(exit_code=0, stdout="", stderr="", oom=False, timed_out=False):
    return ContainerResult(exit_code, stdout, stderr, oom, timed_out, "abc123")


JOB = Job(image="alpine:3.20", command=["echo", "hi"], timeout=7)


# ---------- adapter: Docker result -> JobResult ----------

def test_success_result():
    r = DockerJobExecutor(StubDocker(container(stdout="hi\n"))).run("j", JOB)
    assert r.success and r.kind == FailureKind.NONE
    assert r.stdout == "hi\n"


def test_nonzero_exit_code():
    r = DockerJobExecutor(StubDocker(container(exit_code=3))).run("j", JOB)
    assert not r.success
    assert r.kind == FailureKind.EXIT_CODE and r.exit_code == 3


def test_timeout_wins_over_exit_137():
    r = DockerJobExecutor(StubDocker(container(exit_code=137, timed_out=True))).run("j", JOB)
    assert r.kind == FailureKind.TIMEOUT


def test_oom_result():
    r = DockerJobExecutor(StubDocker(container(exit_code=137, oom=True))).run("j", JOB)
    assert r.kind == FailureKind.OOM


def test_unapproved_image_is_startup_error():
    stub = StubDocker(error=ImageNotApproved("Image 'ubuntu' is not approved"))
    r = DockerJobExecutor(stub).run("j", JOB)
    assert not r.success and r.kind == FailureKind.STARTUP_ERROR


def test_docker_down_is_startup_error():
    stub = StubDocker(error=DockerException("daemon not running"))
    r = DockerJobExecutor(stub).run("j", JOB)
    assert r.kind == FailureKind.STARTUP_ERROR
    assert "daemon not running" in r.message


def test_job_settings_passed_to_docker():
    stub = StubDocker(container())
    DockerJobExecutor(stub).run("j", JOB)
    assert stub.calls[0] == ("alpine:3.20", ["echo", "hi"], 7)


# ---------- scheduler wiring ----------

def test_scheduler_passes_job_definition_to_executor():
    wf = load_workflow("workflows/parallel.yaml")
    ex = FakeExecutor()
    Scheduler.from_workflow(wf).run(ex)
    assert ex.jobs_seen["prepare"].image == "python:3.12-slim"


def test_scheduler_stores_results():
    s = Scheduler({"a": [], "b": ["a"]})
    s.run(FakeExecutor(fail={"a"}))
    assert s.results["a"].kind == FailureKind.EXIT_CODE
    assert "b" not in s.results            # skipped jobs never ran


def test_executor_crash_does_not_crash_scheduler():
    class Exploding:
        def run(self, job_id, job):
            raise ValueError("boom")

    s = Scheduler({"a": [], "b": ["a"]})
    s.run(Exploding())
    assert s.state["a"] == JobState.FAILED
    assert s.results["a"].kind == FailureKind.INTERNAL_ERROR
    assert s.state["b"] == JobState.SKIPPED


def test_startup_error_skips_downstream():
    class StartupFail:
        def run(self, job_id, job):
            return JobResult(False, kind=FailureKind.STARTUP_ERROR, message="no docker")

    s = Scheduler({"a": [], "b": ["a"], "c": ["b"]})
    s.run(StartupFail())
    assert s.state["b"] == JobState.SKIPPED and s.state["c"] == JobState.SKIPPED


def test_full_workflow_through_adapter_without_docker():
    wf = load_workflow("workflows/real-containers.yaml")
    stub = StubDocker(container(stdout="ok"))
    s = Scheduler.from_workflow(wf)
    s.run(DockerJobExecutor(stub))
    assert all(state == JobState.SUCCESS for state in s.state.values())
    assert len(stub.calls) == 4


# ---------- model ----------

def test_timeout_defaults_to_60_and_rejects_zero():
    assert Job(image="a", command=["x"]).timeout == 60
    with pytest.raises(ValidationError):
        Job(image="a", command=["x"], timeout=0)


# ---------- real Docker, end to end ----------

@needs_docker
def test_real_workflow_succeeds():
    wf = load_workflow("workflows/real-containers.yaml")
    s = Scheduler.from_workflow(wf)
    s.run(DockerJobExecutor())
    assert all(state == JobState.SUCCESS for state in s.state.values())
    assert "Test A passed" in s.results["test_a"].stdout


@needs_docker
def test_real_failure_skips_deploy():
    wf = load_workflow("workflows/failure-demo.yaml")
    s = Scheduler.from_workflow(wf)
    s.run(DockerJobExecutor())
    assert s.state["build"] == JobState.SUCCESS
    assert s.state["broken"] == JobState.FAILED
    assert s.results["broken"].kind == FailureKind.EXIT_CODE
    assert s.state["deploy"] == JobState.SKIPPED


@needs_docker
def test_real_timeout():
    wf = load_workflow("workflows/timeout-demo.yaml")
    s = Scheduler.from_workflow(wf)
    s.run(DockerJobExecutor())
    assert s.results["slow"].kind == FailureKind.TIMEOUT
    assert s.state["after"] == JobState.SKIPPED


@needs_docker
def test_cli_run_exit_codes():
    runner = CliRunner()
    assert runner.invoke(app, ["run", "workflows/real-containers.yaml"]).exit_code == 0
    assert runner.invoke(app, ["run", "workflows/failure-demo.yaml"]).exit_code == 1