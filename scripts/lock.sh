#!/bin/sh
# Regenerate the lockfiles from pyproject.toml.
#
# Usage:
#     scripts/lock.sh             # re-lock, keeping current versions where possible
#     scripts/lock.sh --upgrade   # upgrade everything to the latest versions
#     scripts/lock.sh --upgrade-package pillow
#
# Runs pip-compile in the same Python image as the Dockerfile, so the locks
# resolve for the Python version and platform the bot runs on.
set -eu
cd "$(dirname "$0")/.."

image="$(sed -n 's/^FROM //p' Dockerfile | head -n 1)"

docker run --rm -v "$PWD:/src" -w /src -u "$(id -u):$(id -g)" -e HOME=/tmp "$image" sh -c '
    set -eu
    pip install --quiet --user --no-warn-script-location pip-tools
    compile="python -m piptools compile --quiet --strip-extras --generate-hashes --allow-unsafe --no-emit-index-url"
    $compile "$@" -o requirements.txt pyproject.toml
    $compile "$@" --extra dev -c requirements.txt -o requirements-dev.txt pyproject.toml
' sh "$@"
