#!/usr/bin/env bash
# Run tests with coverage report (install requirements-dev.txt first).
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x "./.venv/bin/python" ]]; then
  python="./.venv/bin/python"
else
  python="python"
fi

"$python" -m coverage run manage.py test --settings=config.settings_test "$@"
"$python" -m coverage report
