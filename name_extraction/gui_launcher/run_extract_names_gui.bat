@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pyw "%SCRIPT_DIR%extract_names_gui.py"
    exit /b 0
)

where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "%SCRIPT_DIR%extract_names_gui.py"
    exit /b 0
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" py -3 "%SCRIPT_DIR%extract_names_gui.py"
    exit /b 0
)

python "%SCRIPT_DIR%extract_names_gui.py"
