import yaml

from .models import Workflow, WorkflowError, parse_workflow
from .scheduler import find_cycle_jobs




class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys instead of silently overwriting."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise WorkflowError(
                    f"Duplicate key '{key}' (line {key_node.start_mark.line + 1})"
                )
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_workflow(path: str) -> Workflow:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise WorkflowError(f"Cannot read file: {e}")

    try:
        data = yaml.load(text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as e:
        raise WorkflowError(f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise WorkflowError("Workflow must be a YAML mapping with 'name' and 'jobs'")
    workflow = parse_workflow(data)
    

    _check_dependencies(workflow)
    return workflow


def _check_dependencies(workflow: Workflow) -> None:
    graph = {name: job.needs for name, job in workflow.jobs.items()}

    for name, needs in graph.items():
        for dep in needs:
            if dep == name:
                raise WorkflowError(f"Job '{name}' cannot depend on itself")
            if dep not in graph:
                raise WorkflowError(f"Job '{name}' needs unknown job '{dep}'")

    stuck = find_cycle_jobs(graph)
    if stuck:
        raise WorkflowError(f"Cycle detected involving jobs: {', '.join(sorted(stuck))}")