from collections import deque

from collections import deque

from .executor import Executor
from .models import JobState

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
    """Decides which jobs are ready and tracks every job's state.
    graph maps job -> list of jobs it needs."""

    def __init__(self, graph: dict[str, list[str]]) -> None:
        self.graph = graph
        self.state = {job: JobState.PENDING for job in graph}
        self.dependents: dict[str, list[str]] = {job: [] for job in graph}
        for job, needs in graph.items():
            for dep in needs:
                self.dependents[dep].append(job)

    def ready_jobs(self) -> list[str]:
        """PENDING jobs whose needs are all SUCCESS."""
        return [
            job
            for job, state in self.state.items()
            if state == JobState.PENDING
            and all(self.state[dep] == JobState.SUCCESS for dep in self.graph[job])
        ]

    def mark_success(self, job: str) -> None:
        self.state[job] = JobState.SUCCESS

    def mark_failed(self, job: str) -> None:
        self.state[job] = JobState.FAILED
        self._skip_downstream(job)

    def _skip_downstream(self, failed: str) -> None:
        """Mark everything that depends on `failed` (directly or not) as SKIPPED."""
        stack = list(self.dependents[failed])
        while stack:
            job = stack.pop()
            if self.state[job] == JobState.PENDING:
                self.state[job] = JobState.SKIPPED
                stack.extend(self.dependents[job])

    def is_finished(self) -> bool:
        return all(state in TERMINAL for state in self.state.values())

    def run(self, executor: Executor) -> list[list[str]]:
        """Run the whole workflow. Returns the waves of jobs that ran."""
        waves: list[list[str]] = []
        while not self.is_finished():
            ready = self.ready_jobs()
            if not ready:
                raise RuntimeError("Scheduler stuck: no ready jobs but workflow unfinished")
            waves.append(ready)

            for job in ready:
                self.state[job] = JobState.READY
            for job in ready:
                self.state[job] = JobState.RUNNING
                if executor.run(job):
                    self.mark_success(job)
                else:
                    self.mark_failed(job)
        return waves