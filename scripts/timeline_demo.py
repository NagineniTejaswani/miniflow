from pathlib import Path

from miniflow.docker_executor import DockerJobExecutor
from miniflow.parser import load_workflow
from miniflow.scheduler import Scheduler
from miniflow.timeline import format_timeline


def run_with(limit: int) -> str:
    wf = load_workflow("workflows/overlap-demo.yaml")
    s = Scheduler.from_workflow(wf, max_concurrency=limit)
    s.run(DockerJobExecutor())
    total = max(t.end for t in s.timeline.values())
    a, b = s.timeline["slow_a"], s.timeline["slow_b"]
    return (
        f"max_concurrency = {limit}\n"
        f"{format_timeline(s.timeline)}\n"
        f"total wall time : {total:.2f}s\n"
        f"slow_a and slow_b overlap: {a.overlaps(b)}\n"
    )


report = run_with(4) + "\n" + run_with(1)
print(report)
Path("docs/parallel-timeline.txt").write_text(report, encoding="utf-8")