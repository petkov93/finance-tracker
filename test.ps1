# Run the test suite with in-memory SQLite (no Supabase required).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

& $python manage.py test --settings=config.settings_test @args
