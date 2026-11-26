"""A pure provider: return task descriptions; do not perform build work here."""


def provide(context):
    components = ("web", "backend")
    tasks = {}
    for action in ("test", "build"):
        for component in components:
            tasks[f"{action}.{component}"] = {
                "description": f"Example {action} for {component}",
                "commands": [["python3", "-c", "import sys; print(*sys.argv[1:])", action, component]],
            }
        tasks[f"{action}.all"] = {"dependencies": [f"{action}.{component}" for component in components]}
    return {"tasks": tasks}
