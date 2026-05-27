# Phase-1 model eval (retrieval + guardrails). Requires .venv-cdp + Supabase.
# Phase-2 agent: .\.venv-cdp\Scripts\python.exe eval/run_agent.py [--demo] [--top-k 8] [--temperature 0.1] [--top-p 1.0]
# Docs: README.md#model-evaluation and eval/README.md
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
