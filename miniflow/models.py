from dataclasses import dataclass, field


class WorkflowError(Exception):
    """Raised when a workflow definition is invalid."""


@dataclass
class Job:
    image: str
    command: list[str]
    needs: list[str] = field(default_factory=list)


@dataclass
class Workflow:
    name: str
    jobs: dict[str, Job]


ALLOWED_JOB_FIELDS = {"image", "command", "needs"}


def _parse_job(name: str, raw) -> Job:
    if not isinstance(raw, dict):
        raise WorkflowError(f"Job '{name}' must be a mapping")

    unknown = set(raw) - ALLOWED_JOB_FIELDS
    if unknown:
        raise WorkflowError(f"Job '{name}' has unknown field(s): {', '.join(sorted(map(str, unknown)))}")

    image = raw.get("image")
    if not isinstance(image, str) or not image.strip():
        raise WorkflowError(f"Job '{name}': 'image' is required and must be a non-empty string")

    command = raw.get("command")
    if (not isinstance(command, list) or not command
            or not all(isinstance(c, str) for c in command)):
        raise WorkflowError(f"Job '{name}': 'command' must be a non-empty list of strings")

    needs = raw.get("needs", [])
    if not isinstance(needs, list) or not all(isinstance(n, str) for n in needs):
        raise WorkflowError(f"Job '{name}': 'needs' must be a list of job names")

    return Job(image=image, command=command, needs=needs)


def parse_workflow(data: dict) -> Workflow:
    unknown = set(data) - {"name", "jobs"}
    if unknown:
        raise WorkflowError(f"Unknown top-level field(s): {', '.join(sorted(map(str, unknown)))}")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowError("'name' is required and must be a non-empty string")

    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, dict) or not raw_jobs:
        raise WorkflowError("'jobs' is required and must contain at least one job")

    jobs = {}
    for job_name, raw in raw_jobs.items():
        if not isinstance(job_name, str):
            raise WorkflowError(f"Job name '{job_name}' must be a string")
        jobs[job_name] = _parse_job(job_name, raw)

    return Workflow(name=name, jobs=jobs)