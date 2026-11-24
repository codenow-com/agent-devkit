# uv for the cn-* commands: the tenant's PyPI index from pip.conf, the local Python environment. Sourced after
# common.sh, not run. The index URLs can hold user:token@: they go into the environment of this process only, are
# never printed unmasked and never written to a file (lib/uv_env.py).

# cn_uv_env: export UV_EXTRA_INDEX_URL and UV_INDEX_STRATEGY (from pip.conf) and, on Linux, UV_LINK_MODE=hardlink.
# A value the user set stays.
cn_uv_env() {
  local out
  out="$(python3 -I "$DEVKIT_DIR/lib/uv_env.py" exports)" || return 1
  eval "$out"
}

# cn_uv_indexes: one line with the indexes uv uses, credentials masked.
cn_uv_indexes() { python3 -I "$DEVKIT_DIR/lib/uv_env.py" show; }

# cn_mask: stdin to stdout with user:token@ in URLs masked (for the output of uv and pip).
cn_mask() { sed -E 's#://[^/@ ]*@#://***@#g'; }

# cn_uv_cache_size: the size of uv's cache folder (du -sh), or "empty".
cn_uv_cache_size() {
  local dir
  dir="$(uv cache dir 2>/dev/null)" || { echo "unknown"; return 0; }
  if [ -d "$dir" ]; then du -sh "$dir" 2>/dev/null | cut -f1 | tr -d ' '; else echo "empty"; fi
}
