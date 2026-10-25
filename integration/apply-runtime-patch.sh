#!/usr/bin/env bash
# Apply only the task-scoped runtime injection/observability seam to an upstream checkout.
set -euo pipefail
host_dir="${1:?Usage: apply-runtime-patch.sh /path/to/openpoke}"
patch_file="$(cd "$(dirname "$0")" && pwd)/openpoke-runtime.patch"
if git -C "$host_dir" apply --reverse --check "$patch_file" 2>/dev/null; then
  echo 'OpenPoke runtime patch is already applied.'
else
  git -C "$host_dir" apply --check "$patch_file"
  git -C "$host_dir" apply "$patch_file"
  echo 'Applied task-scoped execution dependency and outcome hooks.'
fi
