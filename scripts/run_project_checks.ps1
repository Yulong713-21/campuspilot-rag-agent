$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}

Push-Location $repoRoot
try {
    & $python -m unittest discover -s tests -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $python -m pip check
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
