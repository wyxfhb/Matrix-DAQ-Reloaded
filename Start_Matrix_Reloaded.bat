@echo off
REM Author: T. Onkst | Date: 05142026
REM Double-click launcher for running Matrix Reloaded from a source checkout.

setlocal

set "APP_NAME=Matrix Reloaded"
set "APP_ROOT=%~dp0"
set "VENV_DIR=%APP_ROOT%.venv"
set "LOG_DIR=%ProgramData%\PSI\Matrix_Reloaded\logs"

cd /d "%APP_ROOT%"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%LOG_DIR%" (
    set "LOG_DIR=%TEMP%\Matrix_Reloaded\logs"
    if not exist "%TEMP%\Matrix_Reloaded\logs" mkdir "%TEMP%\Matrix_Reloaded\logs" >nul 2>&1
)
set "LOG_FILE=%LOG_DIR%\source_launcher.log"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [%DATE% %TIME%] ERROR: Local virtual environment not found: "%VENV_DIR%" > "%LOG_FILE%"
    echo.
    echo %APP_NAME% could not start.
    echo.
    echo Local virtual environment was not found:
    echo   "%VENV_DIR%"
    echo.
    echo Please make sure this station has the project .venv set up before launching.
    echo.
    pause
    exit /b 1
)

set "PYTHON_CONSOLE=%VENV_DIR%\Scripts\python.exe"
set "PYTHON_WINDOWED=%VENV_DIR%\Scripts\pythonw.exe"
if not exist "%PYTHON_WINDOWED%" set "PYTHON_WINDOWED=%PYTHON_CONSOLE%"

echo [%DATE% %TIME%] Starting %APP_NAME% from "%APP_ROOT%" > "%LOG_FILE%"

if /i "%~1"=="--debug" goto debug
if /i "%~1"=="/debug" goto debug

start "%APP_NAME%" /D "%APP_ROOT%" "%PYTHON_WINDOWED%" -m src.ui.app
exit /b 0

:debug
echo Debug launcher mode. Output will stay in this window.
echo Log file: "%LOG_FILE%"
echo.
"%PYTHON_CONSOLE%" -m src.ui.app
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo %APP_NAME% exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
