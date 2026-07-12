# Run tests with coverage report (install requirements-dev.txt first).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

& $python -m coverage run manage.py test @args
& $python -m coverage report
