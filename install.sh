#!/usr/bin/env bash
# Installs the CodeNOW agent devkit: the cn-* commands for developing AI agents on CodeNOW.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/codenow-com/agent-devkit/HEAD/install.sh)"
#
# Or, to read it first: git clone https://github.com/codenow-com/agent-devkit.git && ./agent-devkit/install.sh
#
# It clones the devkit into ~/.codenow/devkit (the newest release tag), links the commands into ~/.local/bin and
# needs no sudo. Run it again to update. Environment: CODENOW_HOME, CODENOW_BIN_DIR, CODENOW_DEVKIT_REPO.
set -euo pipefail

repo="${CODENOW_DEVKIT_REPO:-https://github.com/codenow-com/agent-devkit.git}"
home_dir="${CODENOW_HOME:-$HOME/.codenow}"
dest="$home_dir/devkit"
bin_dir="${CODENOW_BIN_DIR:-$HOME/.local/bin}"

die() { echo "install: $*" >&2; exit 1; }
case "$(uname -s)" in
  Darwin|Linux) ;;
  *) die "macOS or Linux only (on Windows use WSL)" ;;
esac
command -v git >/dev/null 2>&1 || die "git is missing. Install it first: macOS  xcode-select --install ; Ubuntu/Debian  sudo apt-get install -y git"

mkdir -p "$home_dir" "$bin_dir"
if [ -d "$dest/.git" ]; then
  echo "install: updating $dest"
  git -C "$dest" fetch -q --tags origin
else
  echo "install: cloning $repo into $dest"
  git clone -q "$repo" "$dest"
fi

# The newest release tag; the default branch when the repository has no tag yet.
tag="$(git -C "$dest" tag --list 'v*' --sort=-v:refname | head -n 1)"
if [ -n "$tag" ]; then
  git -C "$dest" checkout -q "$tag"
  echo "install: devkit $tag"
else
  git -C "$dest" checkout -q "$(git -C "$dest" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || echo main)"
  git -C "$dest" pull -q --ff-only || true
  echo "install: devkit $(git -C "$dest" rev-parse --short HEAD) (no release tag yet)"
fi

for cmd in "$dest"/bin/cn-*; do
  ln -sf "$cmd" "$bin_dir/$(basename "$cmd")"
done
echo "install: commands linked into $bin_dir: $(cd "$dest/bin" && ls cn-* | tr '\n' ' ')"

case ":$PATH:" in
  *":$bin_dir:"*)
    echo "install: next, run  cn-setup"
    echo "install: (a shell that was open before the install completes cn-* only after  rehash  in zsh or  hash -r  in bash)"
    ;;
  *)
    case "$(basename "${SHELL:-bash}")" in zsh) rc="~/.zshrc" ;; *) rc="~/.bashrc" ;; esac
    echo "install: $bin_dir is not in PATH. Add it:  echo 'export PATH=\"$bin_dir:\$PATH\"' >> $rc"
    echo "install: then open a new terminal and run  cn-setup"
    ;;
esac
