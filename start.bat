@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip >nul
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if "%~1"=="" (
  .venv\Scripts\python.exe -m odwolania2json run
) else (
  .venv\Scripts\python.exe -m odwolania2json %*
)
endlocal
