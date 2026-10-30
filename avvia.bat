@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Prima esegui installa.bat
    pause
    exit /b 1
)
if not exist ".env" (
    echo Manca il file .env: copia .env.example in .env e scrivi le chiavi.
    pause
    exit /b 1
)
echo Programma avviato. Apri http://localhost:8000 - per fermarlo chiudi questa finestra.
start "" http://localhost:8000
".venv\Scripts\python" -m uvicorn app.main:app --port 8000
pause
