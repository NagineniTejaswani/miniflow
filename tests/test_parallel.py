import threading
import time

import docker
import pytest

from miniflow.executor import FailureKind, JobResult
from miniflow.models import JobState
from miniflow.parser import load_workflow
from miniflow.scheduler import Scheduler
from miniflow.timeline import JobTiming, format_timeline


def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


needs_docker = pytest.mark.skipif(not docker_available(), reason="Docker not running")


class TimedExecutor:
    """Fake executor: each job sleeps `delay` seconds; jobs in `fail` fail.
    Tracks how many jobs are active at once."""

    def __init__(self, delay=0.3, delays=None, fail=None):
        self.delay = delay
        self.delays = delays or {}
        self.fail = fail or set()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, job_id, job):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delays.get(job_id, self.delay))
        finally:
            with self._lock:
                self.active -= 1
        if job_id in self.fail:
            return JobResult(False, exit_code=1, kind=FailureKind.EXIT_CODE,
                             message="exit code 1")
        return JobResult(True, exit_code=0)


class BarrierExecutor:
    """Succeeds only if `parties` jobs are running at the SAME time."""

    def __init__(self, parties, timeout=3.0):
        self.barrier = threading.Barrier(parties, timeout=timeout)

    def run(self, job_id, job):
        try:
            self.barrier.wait()
        except threading.BrokenBarrierError:
            return JobResult(False, kind=FailureKind.INTERNAL_ERROR,
                             message="never overlapped")
        return JobResult(True, exit_code=0)


# ---------- Independent challenge: prove real overlap ----------

def test_barrier_proves_jobs_run_simultaneously():
    """Deterministic: passes only if both jobs were running at the same moment."""
    s = Scheduler({"a": [], "b": []}, max_concurrency=2)
    s.run(BarrierExecutor(parties=2))
    assert s.state["a"] == JobState.SUCCESS
    assert s.state["b"] == JobState.SUCCESS


def test_barrier_fails_when_concurrency_is_one():
    """Control experiment: the barrier test CAN detect sequential execution."""
    s = Scheduler({"a": [], "b": []}, max_concurrency=1)
    s.run(BarrierExecutor(parties=2, timeout=0.5))
    assert s.state["a"] == JobState.FAILED
    assert s.state["b"] == JobState.FAILED


def test_independent_jobs_overlap_in_time():
    s = Scheduler({"a": [], "b": []}, max_concurrency=2)
    s.run(TimedExecutor(delay=0.4))
    assert s.timeline["a"].overlaps(s.timeline["b"])


def test_parallel_is_faster_than_sequential():
    graph = {f"j{i}": [] for i in range(4)}          # 4 jobs x 0.3s

    s = Scheduler(graph, max_concurrency=4)
    s.run(TimedExecutor(delay=0.3))
    parallel_total = max(t.end for t in s.timeline.values())

    s = Scheduler(graph, max_concurrency=1)
    s.run(TimedExecutor(delay=0.3))
    sequential_total = max(t.end for t in s.timeline.values())

    assert sequential_total >= 1.2
    assert parallel_total < sequential_total * 0.6


def test_sequential_jobs_do_not_overlap_with_limit_one():
    s = Scheduler({"a": [], "b": []}, max_concurrency=1)
    s.run(TimedExecutor(delay=0.2))
    assert not s.timeline["a"].overlaps(s.timeline["b"])


# ---------- Concurrency limit ----------

def test_concurrency_limit_is_respected():
    graph = {f"j{i}": [] for i in range(6)}
    ex = TimedExecutor(delay=0.15)
    s = Scheduler(graph, max_concurrency=2)
    s.run(ex)
    assert ex.max_active == 2
    assert s.peak_concurrency == 2
    assert all(state == JobState.SUCCESS for state in s.state.values())


def test_invalid_concurrency_rejected():
    with pytest.raises(ValueError):
        Scheduler({"a": []}, max_concurrency=0)


# ---------- Dependencies and failures still correct ----------

def test_dependencies_respected_while_parallel():
    graph = {"prepare": [], "test_a": ["prepare"], "test_b": ["prepare"],
             "report": ["test_a", "test_b"]}
    s = Scheduler(graph, max_concurrency=4)
    s.run(TimedExecutor(delay=0.2))
    t = s.timeline
    assert t["prepare"].end <= t["test_a"].start
    assert t["prepare"].end <= t["test_b"].start
    assert t["test_a"].overlaps(t["test_b"])
    assert max(t["test_a"].end, t["test_b"].end) <= t["report"].start


def test_failure_skips_downstream_in_parallel():
    graph = {"x": [], "y": [], "after_x": ["x"], "after_y": ["y"]}
    s = Scheduler(graph, max_concurrency=2)
    s.run(TimedExecutor(delay=0.1, fail={"x"}))
    assert s.state["x"] == JobState.FAILED
    assert s.state["after_x"] == JobState.SKIPPED
    assert s.state["y"] == JobState.SUCCESS
    assert s.state["after_y"] == JobState.SUCCESS


def test_failure_does_not_cancel_running_sibling():
    ex = TimedExecutor(delays={"fast_fail": 0.05, "slow_ok": 0.4}, fail={"fast_fail"})
    s = Scheduler({"fast_fail": [], "slow_ok": []}, max_concurrency=2)
    s.run(ex)
    assert s.state["fast_fail"] == JobState.FAILED
    assert s.state["slow_ok"] == JobState.SUCCESS


def test_fast_branch_not_blocked_by_slow_sibling():
    """Why waves were dropped: C needs only A, so it must not wait for slow B."""
    graph = {"a": [], "b": [], "c": ["a"]}
    ex = TimedExecutor(delays={"a": 0.05, "b": 0.6, "c": 0.05})
    s = Scheduler(graph, max_concurrency=3)
    s.run(ex)
    assert s.timeline["c"].start < s.timeline["b"].end


def test_workflow_always_reaches_terminal_state():
    graph = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
    s = Scheduler(graph, max_concurrency=4)
    s.run(TimedExecutor(delay=0.05, fail={"b"}))
    assert s.is_finished()


# ---------- Timeline helpers ----------

def test_overlap_logic():
    a, b, c = JobTiming(0, 2), JobTiming(1, 3), JobTiming(2, 4)
    assert a.overlaps(b)
    assert not a.overlaps(c)        # touching edges is not overlap


def test_format_timeline_lists_every_job():
    text = format_timeline({"a": JobTiming(0, 1), "b": JobTiming(0.5, 2)})
    assert "a" in text and "b" in text and "█" in text


# ---------- Real Docker ----------

@needs_docker
def test_real_containers_overlap():
    from miniflow.docker_executor import DockerJobExecutor
    wf = load_workflow("workflows/overlap-demo.yaml")
    s = Scheduler.from_workflow(wf, max_concurrency=4)
    s.run(DockerJobExecutor())
    assert all(state == JobState.SUCCESS for state in s.state.values())
    assert s.timeline["slow_a"].overlaps(s.timeline["slow_b"])