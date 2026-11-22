import docker
import pytest
from docker.errors import NotFound

from miniflow.docker_executor import DockerExecutor, ImageNotApproved


def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


needs_docker = pytest.mark.skipif(not docker_available(), reason="Docker not running")


@pytest.fixture
def ex():
    return DockerExecutor()


def test_unapproved_image_rejected():
    with pytest.raises(ImageNotApproved):
        DockerExecutor().run("ubuntu:latest", ["echo", "hi"])


@needs_docker
def test_success_captures_stdout(ex):
    r = ex.run("alpine:3.20", ["echo", "hello"])
    assert r.success
    assert r.exit_code == 0
    assert r.stdout.strip() == "hello"


@needs_docker
def test_failure_exit_code(ex):
    r = ex.run("alpine:3.20", ["sh", "-c", "exit 3"])
    assert not r.success
    assert r.exit_code == 3
    assert r.reason == "exit code 3"


@needs_docker
def test_stdout_and_stderr_are_separate(ex):
    r = ex.run("alpine:3.20", ["sh", "-c", "echo out; echo err 1>&2"])
    assert r.stdout.strip() == "out"
    assert r.stderr.strip() == "err"


@needs_docker
def test_container_is_removed_after_run(ex):
    r = ex.run("alpine:3.20", ["echo", "bye"])
    with pytest.raises(NotFound):
        ex.client.containers.get(r.container_id)


@needs_docker
def test_container_removed_even_on_failure(ex):
    r = ex.run("alpine:3.20", ["sh", "-c", "exit 1"])
    with pytest.raises(NotFound):
        ex.client.containers.get(r.container_id)


@needs_docker
def test_timeout_kills_container(ex):
    r = ex.run("alpine:3.20", ["sleep", "30"], timeout=2)
    assert r.timed_out
    assert not r.success
    assert r.reason == "timed out"


@needs_docker
def test_memory_limit_causes_oom_kill(ex):
    r = ex.run(
        "python:3.12-slim",
        ["python", "-c", "x = b'x' * (300 * 1024 * 1024)"],
        mem_limit="64m",
    )
    assert r.oom_killed
    assert r.exit_code == 137
    assert r.reason == "out of memory"


@needs_docker
def test_job_within_memory_limit_succeeds(ex):
    r = ex.run(
        "python:3.12-slim",
        ["python", "-c", "x = b'x' * (5 * 1024 * 1024); print('ok')"],
        mem_limit="128m",
    )
    assert r.success
    assert r.stdout.strip() == "ok"