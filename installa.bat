@echo off
setlocal
cd /d "%~dp0"
echo.
echo === Installazione Testreferto ===
echo.

rem Python gia installato: si usa "py" se c'e, altrimenti "python"
set PY=python
where py >nul 2>nul && set PY=py
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || (
    echo Serve Python 3.10 o successivo. Versione trovata:
    %PY% --version
    goto errore
)

echo [1/4] Ambiente Python del progetto (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto errore
)

echo [2/4] Librerie (qualche minuto)...
".venv\Scripts\python" -m pip install --upgrade pip --quiet || goto errore
".venv\Scripts\python" -m pip install -r requirements.txt --quiet || goto errore

echo [3/4] Browser per Sinfonia4You (circa 150 MB)...
".venv\Scripts\python" -m playwright install chromium || goto errore

echo [4/4] File delle impostazioni...
if exist ".env" (
    echo Il file .env esiste gia: non viene toccato.
) else (
    copy ".env.example" ".env" >nul
    echo Creato il file .env: aprilo con il Blocco note e scrivi le chiavi.
)

echo.
echo === Installazione completata ===
echo Il programma NON e stato avviato. Quando vuoi usarlo: doppio clic su avvia.bat
echo.
pause
exit /b 0

:errore
echo.
echo *** ERRORE durante l'installazione: copia il messaggio qui sopra. ***
echo.
pause
exit /b 1
