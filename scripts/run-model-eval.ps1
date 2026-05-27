# Phase-1 model eval (retrieval + guardrails). Requires .venv-cdp + Supabase.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv-cdp\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "CDP venv not found. Run: .\scripts\setup-cdp-venv.ps1" -ForegroundColor Yellow
    exit 1
}

Set-Location $Root
& $Python eval/run_retrieval_guardrails.py @args
exit $LASTEXITCODE
