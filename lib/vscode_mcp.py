"""Adds the CodeNOW MCP server to the user-level mcp.json of VS Code (and VS Code Insiders) for Copilot Chat.

    vscode_mcp.py check <name> <url>    report only
    vscode_mcp.py apply <name> <url>    add the server where it is missing

The file keeps no key: the header takes ${input:codenow-api-key}, so VS Code asks for the key once and keeps it in its
own secret storage. An existing file is merged, never replaced: other servers and inputs stay. A file with comments
(JSONC) or one that does not parse is not touched; the command prints the snippet to add by hand.
Exit code: 0 when every found VS Code has the server (or none is installed), 1 otherwise.
CN_VSCODE_USER_DIRS (paths separated by ":") replaces the default VS Code user folders, for tests.
"""
import json
import os
import pathlib
import platform
import sys

INPUT_ID = "codenow-api-key"


def user_dirs():
    override = os.environ.get("CN_VSCODE_USER_DIRS")
    if override is not None:
        return [pathlib.Path(p) for p in override.split(":") if p]
    home = pathlib.Path.home()
    base = home / "Library" / "Application Support" if platform.system() == "Darwin" else home / ".config"
    return [base / name / "User" for name in ("Code", "Code - Insiders")]


def has_comments(text):
    """True when the text holds // or /* */ outside JSON strings."""
    in_string = escaped = False
    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "/" and text[i + 1:i + 2] in ("/", "*"):
            return True
    return False


def entry(url):
    return {"type": "http", "url": url, "headers": {"X-Codenow-Api-Key": "${input:%s}" % INPUT_ID}}


def input_entry():
    return {"type": "promptString", "id": INPUT_ID, "description": "CodeNOW API key (CodeNOW UI: profile > API keys)",
            "password": True}


def snippet(name, url):
    return json.dumps({"servers": {name: entry(url)}, "inputs": [input_entry()]}, indent=2)


def handle(user_dir, name, url, apply):
    """One VS Code: returns (ok, message)."""
    label = "VS Code Insiders" if "Insiders" in str(user_dir) else "VS Code"
    path = user_dir / "mcp.json"
    text = path.read_text() if path.is_file() else ""
    if url in text:
        return True, f"{label}: CodeNOW MCP ok"
    if not apply:
        return False, f"{label}: CodeNOW MCP missing for Copilot Chat"
    if text.strip():
        if has_comments(text):
            return False, (f"{label}: {path} has comments, so it was not changed. Add this by hand:\n"
                           + snippet(name, url))
        try:
            data = json.loads(text)
        except ValueError:
            return False, f"{label}: {path} does not parse, so it was not changed. Add this by hand:\n" + snippet(name, url)
        if not isinstance(data, dict):
            return False, f"{label}: {path} is not a JSON object, so it was not changed. Add this by hand:\n" + snippet(
                name, url)
    else:
        data = {}
    servers = data.setdefault("servers", {})
    key, n = name, 1
    while key in servers:  # a server with this name but another URL stays; ours gets a free name
        n += 1
        key = f"{name}-{n}"
    servers[key] = entry(url)
    inputs = data.setdefault("inputs", [])
    if not any(isinstance(i, dict) and i.get("id") == INPUT_ID for i in inputs):
        inputs.append(input_entry())
    user_dir.mkdir(parents=True, exist_ok=True)
    if text.strip():
        (user_dir / "mcp.json.bak").write_text(text)
    tmp = user_dir / "mcp.json.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)
    return True, (f"{label}: added MCP server {key} for Copilot Chat; VS Code asks for the CodeNOW API key when the "
                  "server starts (MCP: List Servers > Start)")


def main(argv):
    if len(argv) != 3 or argv[0] not in ("check", "apply"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    mode, name, url = argv
    found = [d for d in user_dirs() if d.parent.is_dir()]  # the Code folder exists once VS Code ran
    all_ok = True
    for user_dir in found:
        ok, message = handle(user_dir, name, url, mode == "apply")
        print(message)
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
