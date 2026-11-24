import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from .executor import Executor, FailureKind, JobResult
from .models import Job, JobState, Workflow
from .timeline import JobTiming

TERMINAL = {JobState.SUCCESS, JobState.FAILED, JobState.SKIPPED}


def find_cycle_jobs(graph: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm. graph maps job -> jobs it needs.
    Returns jobs that could never run (in or behind a cycle). Empty list = no cycle.
    Time: O(V + E)."""
    waiting = {job: len(needs) for job, needs in graph.items()}
    dependents = {job: [] for job in graph}          # who is waiting on me?
    for job, needs in graph.items():
        for dep in needs:
            dependents[dep].append(job)

    queue = deque(job for job, n in waiting.items() if n == 0)
    while queue:
        job = queue.popleft()
        for child in dependents[job]:
            waiting[child] -= 1
            if waiting[child] == 0:
                queue.append(child)

    return [job for job, n in waiting.items() if n > 0]

class Scheduler:
    """Decides what runs when. Knows nothing about Docker.

    Thread rule: only the thread that calls run() ever changes
    self.state / self.results / self.timeline. Workers just execute and return.
    """

    def __init__(self, graph: dict[str, list[str]],
                 jobs: dict[str, Job] | None = None,
                 max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.graph = graph
        self.jobs = jobs or {}
        self.max_concurrency = max_concurrency
        self.state = {job: JobState.PENDING for job in graph}
        self.results: dict[str, JobResult] = {}
        self.timeline: dict[str, JobTiming] = {}
        self.peak_concurrency = 0
        self.dependents: dict[str, list[str]] = {job: [] for job in graph}
        for job, needs in graph.items():
            for dep in needs:
                self.dependents[dep].append(job)

    @classmethod
    def from_workflow(cls, workflow: Workflow, max_concurrency: int = 4) -> "Scheduler":
        graph = {name: job.needs for name, job in workflow.jobs.items()}
        return cls(graph, jobs=workflow.jobs, max_concurrency=max_concurrency)

    def ready_jobs(self) -> list[str]:
        return [
            job for job, state in self.state.items()
            if state == JobState.PENDING
            and all(self.state[dep] == JobState.SUCCESS for dep in self.graph[job])
        ]

    def mark_success(self, job: str) -> None:
        self.state[job] = JobState.SUCCESS

    def mark_failed(self, job: str) -> None:
        self.state[job] = JobState.FAILED
        self._skip_downstream(job)

    def _skip_downstream(self, failed: str) -> None:
        stack = list(self.dependents[failed])
        while stack:
            job = stack.pop()
            if self.state[job] == JobState.PENDING:
                self.state[job] = JobState.SKIPPED
                stack.extend(self.dependents[job])

    def is_finished(self) -> bool:
        return all(state in TERMINAL for state in self.state.values())

    def _execute(self, executor: Executor, job: str) -> JobResult:
        try:
            return executor.run(job, self.jobs.get(job))
        except Exception as e:   # safety net: one bad job must not crash the engine
            return JobResult(False, kind=FailureKind.INTERNAL_ERROR,
                             message=f"executor crashed: {e}")

    def _timed_execute(self, executor: Executor, job: str,
                       t0: float) -> tuple[JobResult, JobTiming]:
        """Runs in a WORKER thread. Touches no scheduler state."""
        start = time.monotonic() - t0
        result = self._execute(executor, job)
        end = time.monotonic() - t0
        return result, JobTiming(start, end)

    def run(self, executor: Executor) -> None:
        t0 = time.monotonic()
        running: dict[Future, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            while True:
                # 1. Start ready jobs while a free slot exists
                for job in self.ready_jobs():
                    if len(running) >= self.max_concurrency:
                        break                      # no slot: job stays PENDING
                    self.state[job] = JobState.READY
                    self.state[job] = JobState.RUNNING
                    fut = pool.submit(self._timed_execute, executor, job, t0)
                    running[fut] = job
                self.peak_concurrency = max(self.peak_concurrency, len(running))

                # 2. Nothing running: either finished, or stuck
                if not running:
                    if self.is_finished():
                        return
                    raise RuntimeError(
                        "Scheduler stuck: no ready jobs but workflow unfinished")

                # 3. Wait for ANY job to finish, then update state (main thread only)
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in done:
                    job = running.pop(fut)
                    result, timing = fut.result()
                    self.results[job] = result
                    self.timeline[job] = timing
                    if result.success:
                        self.mark_success(job)
                    else:
                        self.mark_failed(job)