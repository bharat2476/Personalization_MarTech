# Run PersonaScale UI with base deps only (works on Python 3.14+)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install -r requirements.txt -q
python -m streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false
