@echo off
cd /d "%~dp0"
set PYTHONUTF8=1

if not exist ".env" (
  echo [!] .env not found. Copy .env.example to .env and set your token.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo [!] Python not found. See README.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
".venv\Scripts\python.exe" bot.py
pause
