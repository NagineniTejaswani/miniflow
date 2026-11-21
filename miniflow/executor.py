from typing import Protocol


class Executor(Protocol):
    """Anything that can run a job. Docker executor (Day 4) will follow this too."""

    def run(self, job_id: str) -> bool:
        """Run the job. Return True on success, False on failure."""
        ...


class FakeExecutor:
    """Pretends to run jobs. Jobs listed in `fail` will fail."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.executed: list[str] = []   # records the real execution order

    def run(self, job_id: str) -> bool:
        self.executed.append(job_id)
        return job_id not in self.fail