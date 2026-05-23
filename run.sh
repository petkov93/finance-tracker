#!/bin/bash
# Apply migrations, seed default categories, and start the app.
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python"
fi

echo "Applying migrations..."
"$PYTHON" manage.py migrate

echo "Seeding default categories..."
"$PYTHON" manage.py seed_categories

echo "Collecting static files..."
"$PYTHON" manage.py collectstatic --noinput

echo "Starting development server on port ${PORT}..."
"$PYTHON" manage.py runserver "0.0.0.0:${PORT}"
