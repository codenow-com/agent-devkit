"""A one-shot VS Code task that starts cn-new-agent's assistant in the integrated terminal when the folder opens.

    vscode_task.py add <folder> <assistant> [args...]     write the task into <folder>/.vscode/tasks.json
    vscode_task.py remove <folder> [--created-file] [--created-dir]

add: the task "CodeNOW: new agent" (runOn folderOpen, detail "cn-devkit: one-shot") runs `remove` on its own entry and
then execs the assistant. An existing tasks.json is merged: other tasks stay, an older cn-devkit task is replaced. A
file with comments (JSONC) or one that does not parse as a JSON object with a "tasks" list is not touched: exit 3.
remove: takes out the cn-devkit task. When no task is left, it deletes tasks.json and .vscode, but only the ones that
add created (the flags it put in the task command). It never changes VS Code settings.
"""
import json
import pathlib
import shlex
import sys

LABEL = "CodeNOW: new agent"
MARK = "cn-devkit: one-shot"
NOT_PLAIN_JSON = 3


def load(path):
    """The parsed file, or None when it is not a plain JSON object with an optional "tasks" list."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tasks", []), list):
        return None
    return data


def is_ours(task):
    return isinstance(task, dict) and str(task.get("detail", "")).startswith("cn-devkit:")


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def add(folder, argv):
    vscode = folder / ".vscode"
    path = vscode / "tasks.json"
    created_dir = not vscode.exists()
    created_file = not path.exists()
    if created_file:
        data = {"version": "2.0.0", "tasks": []}
    else:
        data = load(path)
        if data is None:
            return NOT_PLAIN_JSON
        # a second run replaces the older task and keeps what that run created
        for old in data.get("tasks", []):
            if is_ours(old):
                created_file = created_file or "--created-file" in str(old.get("command", ""))
                created_dir = created_dir or "--created-dir" in str(old.get("command", ""))
    remove_cmd = ["python3", "-I", str(pathlib.Path(__file__).resolve()), "remove", str(folder)]
    if created_file:
        remove_cmd.append("--created-file")
    if created_dir:
        remove_cmd.append("--created-dir")
    command = "%s; exec %s" % (" ".join(shlex.quote(a) for a in remove_cmd),
                               " ".join(shlex.quote(a) for a in argv))
    task = {
        "label": LABEL,
        "detail": MARK,
        "type": "shell",
        "command": command,
        "presentation": {"reveal": "always", "focus": True, "panel": "dedicated"},
        "runOptions": {"runOn": "folderOpen"},
        "problemMatcher": [],
    }
    data["tasks"] = [t for t in data.get("tasks", []) if not is_ours(t)] + [task]
    vscode.mkdir(exist_ok=True)
    write(path, data)
    return 0


def remove(folder, created_file, created_dir):
    vscode = folder / ".vscode"
    path = vscode / "tasks.json"
    data = load(path) if path.exists() else None
    if data is None:
        return 0
    tasks = data.get("tasks", [])
    kept = [t for t in tasks if not is_ours(t)]
    if len(kept) == len(tasks):
        return 0
    if not kept and created_file and set(data) <= {"version", "tasks"}:
        path.unlink()
        if created_dir:
            try:
                vscode.rmdir()                      # only when empty
            except OSError:
                pass
        return 0
    data["tasks"] = kept
    write(path, data)
    return 0


def main(args):
    if len(args) >= 3 and args[0] == "add":
        return add(pathlib.Path(args[1]), args[2:])
    if len(args) >= 2 and args[0] == "remove":
        flags = set(args[2:])
        return remove(pathlib.Path(args[1]), "--created-file" in flags, "--created-dir" in flags)
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
