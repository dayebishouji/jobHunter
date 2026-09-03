@echo off
rem jobHunter one-click launcher (Windows)
rem   scripts\run                       -> interactive (prompts for company/position/city)
rem   scripts\run -c "Company" -p "Role" -> non-interactive, --no-open by default
rem   scripts\run -c "X" --no-judicial   -> skip judicial domain
rem
rem Prereqs: project root has .venv activated and `pip install -e .` done,
rem and .env is filled with API keys.

cd /d "%~dp0\.."

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [run] .venv not found: %PY%
    echo [run] First-time setup:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -e .
    exit /b 1
)

if "%~1"=="" (
    "%PY%" -m jobhunter
) else (
    "%PY%" -m jobhunter run --no-open %*
)