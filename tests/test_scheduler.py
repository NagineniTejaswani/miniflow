from miniflow.executor import FakeExecutor
from miniflow.models import JobState
from miniflow.parser import load_workflow
from miniflow.scheduler import Scheduler


def normalize(waves):
    """Sort inside each wave so tests don't depend on dict order."""
    return [sorted(w) for w in waves]


def test_linear_chain_runs_in_order():
    s = Scheduler({"a": [], "b": ["a"], "c": ["b"]})
    ex = FakeExecutor()
    s.run(ex)
    assert ex.executed == ["a", "b", "c"]


def test_dependency_order_in_timeline():
    graph = {
        "prepare": [],
        "test_a": ["prepare"],
        "test_b": ["prepare"],
        "report": ["test_a", "test_b"],
    }
    s = Scheduler(graph)
    s.run(FakeExecutor())
    t = s.timeline
    assert t["prepare"].end <= t["test_a"].start
    assert t["prepare"].end <= t["test_b"].start
    assert max(t["test_a"].end, t["test_b"].end) <= t["report"].start


def test_join_waits_for_all_dependencies():
    s = Scheduler({"a": [], "b": [], "c": ["a", "b"]})
    s.mark_success("a")
    assert s.ready_jobs() == ["b"]          # c must NOT be ready yet
    s.mark_success("b")
    assert s.ready_jobs() == ["c"]


def test_independent_jobs_all_ready_at_start():
    s = Scheduler({"a": [], "b": [], "c": []})
    assert sorted(s.ready_jobs()) == ["a", "b", "c"]


def test_failure_skips_direct_dependent():
    s = Scheduler({"build": [], "test": ["build"]})
    s.run(FakeExecutor(fail={"build"}))
    assert s.state["build"] == JobState.FAILED
    assert s.state["test"] == JobState.SKIPPED


def test_failure_skips_transitive_dependents():
    s = Scheduler({"build": [], "test": ["build"], "deploy": ["test"]})
    ex = FakeExecutor(fail={"build"})
    s.run(ex)
    assert s.state["deploy"] == JobState.SKIPPED
    assert ex.executed == ["build"]          # nothing else was ever run


def test_independent_branch_still_runs_after_failure():
    graph = {
        "build": [],
        "lint": ["build"],
        "test": ["build"],
        "package": ["lint", "test"],
    }
    s = Scheduler(graph)
    s.run(FakeExecutor(fail={"test"}))
    assert s.state["lint"] == JobState.SUCCESS      # unaffected branch
    assert s.state["test"] == JobState.FAILED
    assert s.state["package"] == JobState.SKIPPED   # needs the failed job


def test_all_jobs_end_in_terminal_state():
    s = Scheduler({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
    s.run(FakeExecutor(fail={"b"}))
    assert s.is_finished()
    assert s.state["c"] == JobState.SUCCESS
    assert s.state["d"] == JobState.SKIPPED


def test_failed_job_is_not_run_again():
    s = Scheduler({"a": []})
    ex = FakeExecutor(fail={"a"})
    s.run(ex)
    assert ex.executed == ["a"]


def test_scheduler_works_with_real_workflow_file():
    wf = load_workflow("workflows/parallel.yaml")
    graph = {name: job.needs for name, job in wf.jobs.items()}
    ex = FakeExecutor()
    Scheduler(graph).run(ex)
    assert ex.executed[0] == "prepare"
    assert ex.executed[-1] == "report"


def test_failure_demo_workflow_blocks_deploy():
    wf = load_workflow("workflows/failure-demo.yaml")
    graph = {name: job.needs for name, job in wf.jobs.items()}
    s = Scheduler(graph)
    s.run(FakeExecutor(fail={"broken"}))
    assert s.state["build"] == JobState.SUCCESS
    assert s.state["broken"] == JobState.FAILED
    assert s.state["deploy"] == JobState.SKIPPED