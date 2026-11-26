"""Deterministic dependency validation and topological ordering."""
from .model import DevtoolError, Task


class TaskGraph:
    def __init__(self, tasks: dict[str, Task]):
        self.tasks = tasks
        self.order(tuple(tasks))  # Validate disconnected components too.

    def order(self, requested: tuple[str, ...], enabled=None) -> tuple[Task, ...]:
        done: set[str] = set()
        active: list[str] = []
        result: list[Task] = []

        def visit(name: str):
            if name in done:
                return
            if name in active:
                raise DevtoolError("task dependency cycle: " + " -> ".join((*active, name)))
            if name not in self.tasks:
                raise DevtoolError(f"unknown task {name!r}")
            if enabled is not None and not enabled(self.tasks[name]):
                done.add(name)
                return
            active.append(name)
            for dependency in self.tasks[name].dependencies:
                visit(dependency)
            active.pop()
            done.add(name)
            result.append(self.tasks[name])

        for name in requested:
            visit(name)
        return tuple(result)
