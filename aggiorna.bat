@echo off
setlocal
rem Aggiorna il programma all'ultima versione su GitHub. Non tocca .env, .venv ed esplorazione.

rem Il file si copia in una cartella temporanea e riparte da li, perche sta per essere sostituito.
if not "%~1"=="--da-temp" (
    copy /y "%~f0" "%TEMP%\aggiorna_testreferto.bat" >nul
    "%TEMP%\aggiorna_testreferto.bat" --da-temp "%~dp0"
    exit /b
)
set "PROGETTO=%~2"
set "ZIP=%TEMP%\testreferto.zip"
set "ESTRATTO=%TEMP%\testreferto_aggiornamento"
set "URL=https://github.com/eze1007/Testreferto/archive/refs/heads/claude/relaxed-planck-yatgnx.zip"

echo.
echo === Aggiornamento Testreferto ===
echo.
echo [1/3] Scarico l'ultima versione...
if exist "%ESTRATTO%" rmdir /s /q "%ESTRATTO%"
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%'; Expand-Archive -Force '%ZIP%' '%ESTRATTO%'" || goto errore
set "SORGENTE="
for /d %%D in ("%ESTRATTO%\*") do set "SORGENTE=%%D"
if not defined SORGENTE goto errore

echo [2/3] Sostituisco i file del programma...
robocopy "%SORGENTE%" "%PROGETTO%." /E /XD .venv esplorazione /XF .env /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto errore

echo [3/3] Controllo le librerie...
if exist "%PROGETTO%.venv\Scripts\python.exe" (
    "%PROGETTO%.venv\Scripts\python" -m pip install -r "%PROGETTO%requirements.txt" --quiet || goto errore
) else (
    echo Ambiente non ancora installato: esegui installa.bat
)

del "%ZIP%" >nul 2>nul
rmdir /s /q "%ESTRATTO%" >nul 2>nul
echo.
echo === Aggiornamento completato. Il file .env non e stato toccato. ===
echo Per usare il programma: doppio clic su avvia.bat
echo.
pause
exit /b 0

:errore
echo.
echo *** ERRORE durante l'aggiornamento: copia il messaggio qui sopra. ***
echo.
pause
exit /b 1
