# Apply migrations, seed default categories, and start the app.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$port = if ($env:PORT) { $env:PORT } else { "8000" }

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

Write-Host "Applying migrations..."
& $python manage.py migrate

Write-Host "Seeding default categories..."
& $python manage.py seed_categories

Write-Host "Collecting static files..."
& $python manage.py collectstatic --noinput

Write-Host "Starting development server on port $port..."
& $python manage.py runserver "0.0.0.0:$port"
