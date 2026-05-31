#!/usr/bin/env bash
# Run the test suite with in-memory SQLite (no Supabase required).
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x "./.venv/bin/python" ]]; then
  python="./.venv/bin/python"
else
  python="python"
fi

exec "$python" manage.py test --settings=config.settings_test "$@"
