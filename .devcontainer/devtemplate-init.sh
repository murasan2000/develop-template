#!/usr/bin/env bash
#
# Copy the shared lint / formatter configs baked into the image into the current
# project, skipping any file that already exists.
#
#   devtemplate-init          # copy missing configs
#   devtemplate-init --force  # overwrite existing ones too
#   devtemplate-init --list   # show what the image ships
set -euo pipefail

SRC=/opt/devtemplate/templates
force=false

case "${1:-}" in
  --force) force=true ;;
  --list)
    ls -1A "$SRC"
    exit 0
    ;;
  --help | -h)
    sed -n '2,9p' "$0" | sed 's/^# \?//'
    exit 0
    ;;
  "") ;;
  *)
    echo "unknown option: $1" >&2
    exit 2
    ;;
esac

for src in "$SRC"/* "$SRC"/.[!.]*; do
  [ -e "$src" ] || continue
  name="$(basename "$src")"
  if [ -e "./$name" ] && [ "$force" != true ]; then
    printf '  skip    %s (already exists)\n' "$name"
    continue
  fi
  cp "$src" "./$name"
  printf '  copied  %s\n' "$name"
done
