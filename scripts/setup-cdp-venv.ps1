# Creates .venv-cdp with Python 3.12 (or 3.11) and installs requirements-cdp.txt
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PythonCmd = $null
foreach ($ver in @("3.12", "3.11")) {
    try {
        $probe = & py "-$ver" -c "import sys; print(sys.version)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = "py -$ver"
            Write-Host "Using Python ${ver}: $probe"
            break
        }
    } catch { }
}

if (-not $PythonCmd) {
    Write-Error @"
Python 3.12 or 3.11 not found via 'py' launcher.

Option A (recommended on Windows 10/11):
  py install 3.12
  .\scripts\setup-cdp-venv.ps1

Option B:
  Install from https://www.python.org/downloads/ (check 'py launcher' + 'Add to PATH')
  Then re-run: .\scripts\setup-cdp-venv.ps1
"@
}

$VenvPath = Join-Path $Root ".venv-cdp"
if (-not (Test-Path $VenvPath)) {
    Invoke-Expression "$PythonCmd -m venv `"$VenvPath`""
    Write-Host "Created virtual environment at $VenvPath"
}

$Activate = Join-Path $VenvPath "Scripts\Activate.ps1"
. $Activate

python -m pip install --upgrade pip
pip install -r requirements-cdp.txt
if (Test-Path "requirements-agent.txt") {
    pip install -r requirements-agent.txt
}

Write-Host ""
Write-Host "CDP venv ready. Activate with:"
Write-Host "  .\.venv-cdp\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Add SUPABASE_KEY to .env (Project Settings -> API in Supabase), then test:"
Write-Host '  # .env already has SUPABASE_URL if you configured the project'
Write-Host '  python -c "from cdp_pipeline import get_supabase_client; get_supabase_client(); print(''OK'')"'
Write-Host '  python -c "from cdp_pipeline import compile_agent_context; print(compile_agent_context(''USER_7721'', ''hydration vest marathon''))"'
