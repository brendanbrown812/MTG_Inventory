@echo off
setlocal
set "ROOT=%~dp0"

echo.
echo  Spellbinder — startup checks
echo  -----------------------------
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js was not found on PATH.
  echo.
  echo         Install Node 20 LTS from https://nodejs.org/
  echo         ^(use the Windows Installer and enable "Add to PATH"^)
  goto :fail
)

node -e "process.exit(parseInt(process.versions.node.split('.')[0],10)>=18?0:1)" 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 18 or newer is required. Vite 5 will not run on older Node.
  echo.
  for /f "delims=" %%v in ('node -v 2^>nul') do echo         Your version: %%v
  echo         Install Node 20 LTS from https://nodejs.org/  then close ALL
  echo         Command Prompt windows and try again.
  echo.
  echo         ^(Errors like "Unexpected token '??='" mean Node is too old.^)
  goto :fail
)

set "PYTHON_MODE="
if exist "%ROOT%backend\.venv\Scripts\python.exe" (
  "%ROOT%backend\.venv\Scripts\python.exe" --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_MODE=venv"
)

if not defined PYTHON_MODE (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_MODE=py"
)

if not defined PYTHON_MODE (
  python --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_MODE=python"
)

if not defined PYTHON_MODE (
  echo [ERROR] Python 3 was not found.
  echo.
  echo         Windows has a "py" launcher, but it is not connected to an
  echo         installed Python runtime. Install Python 3.12 from:
  echo         https://www.python.org/downloads/windows/
  echo.
  echo         During setup, enable "Add python.exe to PATH", then run this
  echo         launcher again.
  goto :fail
)

if "%PYTHON_MODE%"=="venv" (
  "%ROOT%backend\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, pydantic, httpx, openai" >nul 2>&1
) else if "%PYTHON_MODE%"=="py" (
  py -3 -c "import fastapi, uvicorn, sqlalchemy, pydantic, httpx, openai" >nul 2>&1
) else (
  python -c "import fastapi, uvicorn, sqlalchemy, pydantic, httpx, openai" >nul 2>&1
)
if errorlevel 1 (
  echo [ERROR] One or more backend Python dependencies are missing.
  echo.
  if "%PYTHON_MODE%"=="venv" (
    echo         Run:
    echo           "%ROOT%backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%backend\requirements.txt"
  ) else if "%PYTHON_MODE%"=="py" (
    echo         Run:
    echo           cd /d "%ROOT%backend"
    echo           py -3 -m pip install -r requirements.txt
  ) else (
    echo         Run:
    echo           cd /d "%ROOT%backend"
    echo           python -m pip install -r requirements.txt
  )
  goto :fail
)

netstat -ano 2>nul | findstr "LISTENING" | findstr /C:":8000 " >nul
if not errorlevel 1 (
  echo [ERROR] Port 8000 is already in use. The API cannot start twice.
  echo.
  echo         Fix: close the old "Spellbinder — API" console window, OR run:
  echo           netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"
  echo         Note the number in the last column ^(PID^), then:
  echo           taskkill /PID that_number /F
  goto :fail
)

netstat -ano 2>nul | findstr "LISTENING" | findstr /C:":5173 " >nul
if not errorlevel 1 (
  echo [ERROR] Port 5173 is already in use ^(Vite dev server^).
  echo         Close the other "Spellbinder — UI" window or stop whatever is on 5173.
  echo           netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"
  goto :fail
)

echo OK: Node
node -v
echo OK: Ports 8000 and 5173 are free.
echo.
echo Starting API and UI in new windows...
echo.

if "%PYTHON_MODE%"=="venv" (
  start "Spellbinder — API (port 8000)" /D "%ROOT%backend" cmd /k ""%ROOT%backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
) else if "%PYTHON_MODE%"=="py" (
  start "Spellbinder — API (port 8000)" /D "%ROOT%backend" cmd /k py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) else (
  start "Spellbinder — API (port 8000)" /D "%ROOT%backend" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
)

start "Spellbinder — UI (port 5173)" /D "%ROOT%frontend" cmd /k npm run dev

echo Waiting for servers to listen ^(15 sec^)...
timeout /t 15 /nobreak >nul

start "" "http://127.0.0.1:5173/"

echo.
echo Browser opened: http://127.0.0.1:5173/
echo API docs ^(optional^): http://127.0.0.1:8000/docs
echo Close the API and UI console windows to stop the servers.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
