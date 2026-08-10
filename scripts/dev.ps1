$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath '.venv')) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
& .\.venv\Scripts\python.exe -m alpha.dev

