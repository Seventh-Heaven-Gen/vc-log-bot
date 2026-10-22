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

rem pip 26.2.2 (eMudhra/emSign certificate fix), pinned by hash
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
".venv\Scripts\python.exe" bot.py
pause
