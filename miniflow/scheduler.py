from collections import deque


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