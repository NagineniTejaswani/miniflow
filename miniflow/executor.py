from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .models import Job


class FailureKind(str, Enum):
    NONE = "NONE"
    EXIT_CODE = "EXIT_CODE"
    TIMEOUT = "TIMEOUT"
    OOM = "OOM"
    STARTUP_ERROR = "STARTUP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass
class JobResult:
    success: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    kind: FailureKind = FailureKind.NONE
    message: str = "ok"


class Executor(Protocol):
    """The contract. Scheduler depends on this, never on Docker."""

    def run(self, job_id: str, job: Job | None) -> JobResult: ...


class FakeExecutor:
    """Pretends to run jobs. Jobs listed in `fail` will fail."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.executed: list[str] = []
        self.jobs_seen: dict[str, Job | None] = {}

    def run(self, job_id: str, job: Job | None = None) -> JobResult:
        self.executed.append(job_id)
        self.jobs_seen[job_id] = job
        if job_id in self.fail:
            return JobResult(False, exit_code=1, kind=FailureKind.EXIT_CODE,
                             message="exit code 1")
        return JobResult(True, exit_code=0)