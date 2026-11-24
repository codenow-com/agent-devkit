"""The package indexes of pip for uv. uv does not read pip.conf, so the tenant's PyPI index (the CodeNOW Agent SDK is not
on public PyPI) would be missing. Python 3.9+, standard library only.

    python3 -I uv_env.py exports   shell lines for eval: UV_EXTRA_INDEX_URL, UV_INDEX_STRATEGY (and UV_LINK_MODE on Linux)
    python3 -I uv_env.py show      the indexes, with user:token@ masked

The indexes come from pip's own files and variables, in pip's order (a later file wins per key; [install] wins over
[global]): global files, ~/.pip/pip.conf, ~/.config/pip/pip.conf, ~/Library/Application Support/pip/pip.conf,
$VIRTUAL_ENV/pip.conf, PIP_CONFIG_FILE, then PIP_INDEX_URL and PIP_EXTRA_INDEX_URL. Every index except public PyPI
goes to UV_EXTRA_INDEX_URL (extra-index-url first, then public PyPI when pip.conf names it, then index-url), so public
PyPI stays uv's default index and a package that the tenant's index has comes from there. A UV_INDEX, UV_INDEX_URL, UV_DEFAULT_INDEX or UV_EXTRA_INDEX_URL
that is already set is kept: nothing is exported for the indexes then.

The URLs can hold user:token@. `exports` prints them for eval only and refuses a terminal; nothing is written to a file.
"""
import configparser
import os
import platform
import re
import shlex
import sys

PYPI = re.compile(r"^https?://(pypi\.org|pypi\.python\.org|files\.pythonhosted\.org)(/|$)", re.I)
UV_INDEX_VARS = ("UV_INDEX", "UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_EXTRA_INDEX_URL")


def mask(text):
    """user:token@ (or token@) in every URL of the text becomes ***@."""
    return re.sub(r"://[^/@\s]+@", "://***@", text)


def config_files(env):
    home = env.get("HOME") or os.path.expanduser("~")
    files = []
    if platform.system() == "Darwin":
        files.append("/Library/Application Support/pip/pip.conf")
    else:
        for d in (env.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":"):
            if d:
                files.append(os.path.join(d, "pip", "pip.conf"))
        files.append("/etc/pip.conf")
    files.append(os.path.join(home, ".pip", "pip.conf"))
    files.append(os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "pip", "pip.conf"))
    if platform.system() == "Darwin":
        files.append(os.path.join(home, "Library", "Application Support", "pip", "pip.conf"))
    if env.get("VIRTUAL_ENV"):
        files.append(os.path.join(env["VIRTUAL_ENV"], "pip.conf"))
    if env.get("PIP_CONFIG_FILE") and env["PIP_CONFIG_FILE"] != os.devnull:
        files.append(env["PIP_CONFIG_FILE"])
    return files


def pip_settings(env):
    """index-url and extra-index-url as pip sees them: (index_url or None, [extra urls])."""
    if env.get("PIP_CONFIG_FILE") == os.devnull:
        files = []
    else:
        files = config_files(env)
    index, extra = None, None
    for path in files:
        if not os.path.isfile(path):
            continue
        parser = configparser.RawConfigParser()
        try:
            parser.read(path)
        except (configparser.Error, OSError, UnicodeDecodeError):
            continue
        for section in ("global", "install"):
            if not parser.has_section(section):
                continue
            if parser.has_option(section, "index-url"):
                index = parser.get(section, "index-url").strip() or None
            if parser.has_option(section, "extra-index-url"):
                extra = parser.get(section, "extra-index-url").split()
    if env.get("PIP_INDEX_URL"):
        index = env["PIP_INDEX_URL"].strip()
    if env.get("PIP_EXTRA_INDEX_URL"):
        extra = env["PIP_EXTRA_INDEX_URL"].split()
    return index, extra or []


JFROG_REPO = re.compile(r"(/artifactory/api/pypi/[^/\s]+)/?$")


def simple_url(url):
    """A JFrog PyPI repository URL without /simple: pip copes with it, uv does not (JFrog answers the package pages
    with application/octet-stream there), so it gets JFrog's /simple."""
    return JFROG_REPO.sub(r"\1/simple", url)


def tenant_indexes(env):
    """The indexes for UV_EXTRA_INDEX_URL, in the order uv asks them: pip's extra-index-url without public PyPI, then
    public PyPI when pip.conf names it, then pip's index-url. An index-url that is a proxy of PyPI (a JFrog remote) is
    asked only for what PyPI has not: it is much slower than PyPI. Empty when pip.conf has only public PyPI."""
    index, extra = pip_settings(env)
    urls, pypi = [], None
    for url in extra:
        if PYPI.match(url):
            pypi = pypi or url
        else:
            url = simple_url(url)
            if url not in urls:
                urls.append(url)
    if index and not PYPI.match(index):
        index = simple_url(index)
        if pypi:
            urls.append(pypi)
        if index not in urls:
            urls.append(index)
    return urls


def exports(env):
    """name -> value of what the devkit sets for uv; empty when the user set it already."""
    out = {}
    if not any(env.get(name) for name in UV_INDEX_VARS):
        urls = tenant_indexes(env)
        if urls:
            out["UV_EXTRA_INDEX_URL"] = " ".join(urls)
            # A tenant index answers 403 for a package it does not hold, and uv's default strategy (first-index) stops
            # at a 403. unsafe-first-match goes on to the next index but still takes a package from the first index
            # that has it, so the tenant's index keeps the priority over public PyPI.
            if not env.get("UV_INDEX_STRATEGY"):
                out["UV_INDEX_STRATEGY"] = "unsafe-first-match"
    # Hard links from the cache are fast and use no space. macOS keeps uv's default (clone: copy-on-write on APFS).
    if not env.get("UV_LINK_MODE") and platform.system() == "Linux":
        out["UV_LINK_MODE"] = "hardlink"
    return out


def main(argv, env):
    command = argv[1] if len(argv) > 1 else ""
    if command == "exports":
        if sys.stdout.isatty():
            print("uv_env: exports prints credentials; use it only as  eval \"$(python3 -I uv_env.py exports)\"",
                  file=sys.stderr)
            return 2
        for name, value in exports(env).items():
            print(f"export {name}={shlex.quote(value)}")
        return 0
    if command == "show":
        kept = [name for name in UV_INDEX_VARS if env.get(name)]
        if kept:
            print(f"indexes: your {', '.join(kept)} (kept)")
        else:
            urls = tenant_indexes(env)
            if urls:
                print("indexes, in this order: " + ", ".join(mask(u) for u in urls) + ", then public PyPI")
            else:
                print("indexes: public PyPI only (pip.conf names no other index)")
        return 0
    print("usage: uv_env.py exports|show", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv, dict(os.environ)))
