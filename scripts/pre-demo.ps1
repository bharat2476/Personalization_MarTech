# PersonaScale AI - Pre-demo setup and health checks
# Usage: .\scripts\pre-demo.ps1
#        .\scripts\pre-demo.ps1 -StartStreamlit

param(
    [switch]$StartStreamlit,
    [switch]$SkipCdpInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv-cdp\Scripts\python.exe"

function Write-Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  XX  $msg" -ForegroundColor Red }

Write-Host "`n=== PersonaScale AI - Pre-Demo Checklist ===" -ForegroundColor White

Write-Step 1 "Python runtimes"
try {
    py -3.12 --version | ForEach-Object { Write-Ok $_ }
} catch {
    Write-Warn "Python 3.12 not found. Run: py install 3.12"
}
python --version | ForEach-Object { Write-Ok "System: $_" }

Write-Step 2 "Install Streamlit app dependencies"
python -m pip install -r requirements.txt -q
Write-Ok "requirements.txt"

Write-Step 3 "CDP + Agent virtualenv (.venv-cdp)"
if (-not (Test-Path $VenvPython)) {
    if (-not $SkipCdpInstall) {
        Write-Host "  Creating .venv-cdp ..."
        & (Join-Path $Root "scripts\setup-cdp-venv.ps1")
    } else {
        Write-Warn ".venv-cdp missing - run .\scripts\setup-cdp-venv.ps1"
    }
} else {
    Write-Ok ".venv-cdp exists"
}

if (Test-Path $VenvPython) {
    & $VenvPython -m pip install -r requirements-agent.txt -q 2>$null
    Write-Ok "requirements-agent.txt"
}

Write-Step 4 "Environment file (.env)"
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Fail ".env missing - copy .env.example and fill SUPABASE_URL, SUPABASE_KEY"
} else {
    Write-Ok ".env present"
    $envLines = Get-Content $EnvFile -Raw
    if ($envLines -match "SUPABASE_URL=https://") { Write-Ok "SUPABASE_URL set" } else { Write-Warn "SUPABASE_URL missing" }
    if ($envLines -match "SUPABASE_KEY=\S+") { Write-Ok "SUPABASE_KEY set" } else { Write-Warn "SUPABASE_KEY missing" }
    if ($envLines -match "OPENAI_API_KEY=sk-") { Write-Ok "OPENAI_API_KEY set (optional)" } else { Write-Warn "OPENAI_API_KEY not set - Tab 8 works without LLM toggle" }
}

Write-Step 5 "Supabase CDP connectivity"
if (Test-Path $VenvPython) {
    $sb = & $VenvPython -c "from cdp_pipeline import get_supabase_client; get_supabase_client(); print('connected')" 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok $sb } else { Write-Warn "Supabase client failed: $sb" }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $golden = & $VenvPython -c "from cdp_pipeline import stitch_golden_record; r=stitch_golden_record('USER_7721'); print(r.get('external_id', r))" 2>&1
    $goldenOk = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $prevEap
    if ($goldenOk) { Write-Ok "USER_7721 golden record: $golden" }
    else {
        Write-Warn "USER_7721 not found or tables missing."
        Write-Host "       Run in Supabase SQL Editor:" -ForegroundColor DarkGray
        Write-Host "         1) supabase/migrations/20260518120000_cdp_stitched_schema.sql" -ForegroundColor DarkGray
        Write-Host "         2) supabase/seed_demo.sql" -ForegroundColor DarkGray
        Write-Host "         3) .venv-cdp python scripts/backfill_product_embeddings.py" -ForegroundColor DarkGray
    }
} else {
    Write-Warn "Skip - .venv-cdp not available"
}

Write-Step 6 "MarTech agent module"
if (Test-Path $VenvPython) {
    $ag = & $VenvPython -c "from martech_agent import MARTECH_TOOLS; print(len(MARTECH_TOOLS), 'tools')" 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok "martech_agent: $ag" } else { Write-Warn $ag }
}

Write-Host "`n=== BEFORE DEMO - Action items ===" -ForegroundColor White
Write-Host "  * Supabase SQL: run migration + seed_demo.sql"
Write-Host "  * Embeddings:   .venv-cdp\Scripts\python.exe scripts\backfill_product_embeddings.py"
Write-Host "  * .env:         SUPABASE_URL + KEY (use anon eyJ JWT if 401)"
Write-Host "  * Tab 1:        Run Simulation before Tab 8 fallback"
Write-Host "  * Tab 8:        USER_7721 + hydration / shoe suppression prompt"
Write-Host "  * OpenAI:       optional - leave LLM toggle OFF if no billing"
Write-Host "  * URL:          http://localhost:8501"

Write-Host "`n=== Demo flow (5 min) ===" -ForegroundColor White
Write-Host "  > Tab 1 - Member and Strategy, Run Simulation"
Write-Host "  > Tab 2 - Recommendations, View/Click products"
Write-Host "  > Tab 3 - Marketing and Ads, propensity"
Write-Host "  > Tab 8 - GenAI Agent Studio, chat + telemetry + push alert"

if ($StartStreamlit) {
    Write-Host "`nStarting Streamlit at http://localhost:8501 ..." -ForegroundColor Green
    python -m streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false
}
