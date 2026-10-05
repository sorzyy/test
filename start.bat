@echo off
rem Lancement local sous Windows. Prérequis : Python 3.10+ (python.org), ffmpeg et deno.
rem   winget install Gyan.FFmpeg
rem   winget install DenoLand.Deno
cd /d "%~dp0"
where ffmpeg >nul 2>nul || echo [!] ffmpeg introuvable : winget install Gyan.FFmpeg
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if "%PORT%"=="" set PORT=9000
echo saphir sur http://localhost:%PORT%
start "" http://localhost:%PORT%
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
