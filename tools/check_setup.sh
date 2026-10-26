#!/bin/sh
# Bypass Python's site/venv initialization so we can diagnose a broken venv.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin="$script_dir/../.venv/bin/python3"
if [ ! -x "$python_bin" ]; then
    echo "FAIL: No usable .venv/bin/python3. Create the environment using README.md." >&2
    exit 1
fi
exec "$python_bin" -B -S "$script_dir/check_setup.py" --bootstrap "$@"
