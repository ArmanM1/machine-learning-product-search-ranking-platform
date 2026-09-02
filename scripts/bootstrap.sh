#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv_version="0.12.9"
skip_web=0
require_cloud_tools=0

for argument in "$@"; do
  case "${argument}" in
    --skip-web) skip_web=1 ;;
    --require-cloud-tools) require_cloud_tools=1 ;;
    *) echo "Unknown argument: ${argument}" >&2; exit 2 ;;
  esac
done

if command -v python3.11 >/dev/null 2>&1; then
  python_command="$(command -v python3.11)"
elif command -v python >/dev/null 2>&1; then
  python_command="$(command -v python)"
else
  echo "Python 3.11 is required but no Python executable was found." >&2
  exit 1
fi

python_version="$(${python_command} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != "3.11" ]]; then
  echo "Python 3.11 is required; found ${python_version} at ${python_command}." >&2
  exit 1
fi

cd "${repo_root}"
if command -v uv >/dev/null 2>&1; then
  uv_command=("$(command -v uv)")
else
  "${python_command}" -m pip install --user --disable-pip-version-check "uv==${uv_version}"
  uv_command=("${python_command}" -m uv)
fi

"${uv_command[@]}" sync --frozen --extra dev
"${uv_command[@]}" run python -m search_rank.cli --help

if [[ "${skip_web}" -eq 0 ]]; then
  command -v npm >/dev/null 2>&1 || {
    echo "npm is required for the web package; use --skip-web only for backend work." >&2
    exit 1
  }
  npm --prefix web ci --ignore-scripts --no-audit --no-fund
fi

missing=()
for tool in aws terraform docker; do
  command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
done
if [[ "${require_cloud_tools}" -eq 1 && "${#missing[@]}" -gt 0 ]]; then
  echo "Missing required cloud/container tools: ${missing[*]}" >&2
  exit 1
fi
if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "Warning: optional cloud/container tools not found: ${missing[*]}" >&2
fi

echo "Bootstrap complete. No AWS API calls or cloud writes were performed."
