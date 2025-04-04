@echo off
setlocal

REM --- Configuration ---
set APP_DIR=%~dp0
set VENV_NAME=.venv
set VENV_DIR=%APP_DIR%%VENV_NAME%
set PYTHON_EXE=%VENV_DIR%\Scripts\python.exe
set REQUIREMENTS=PyQt6 lmstudio pydantic

REM --- Check for Python ---
echo Checking for Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not found in PATH. Please install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
) else (
    echo Found Python.
)

REM --- Check/Install UV ---
echo Ensuring UV is available (installing/upgrading)...
python -m pip install --upgrade uv
if %errorlevel% neq 0 (
    echo Error: Failed to install or upgrade UV using pip. Check internet connection and pip setup.
    echo Please try installing manually: python -m pip install uv
    pause
    exit /b 1
)

REM --- Verify UV Installation ---
echo Verifying UV installation...
uv --version > nul 2>&1
if %errorlevel% neq 0 (
     echo Error: UV command still not found after installation attempt.
     echo Please check your system's PATH environment variable or try installing manually again.
     pause
     exit /b 1
 ) else (
     echo UV is available.
 )


REM --- Create/Update Virtual Environment ---
echo Setting up virtual environment in %VENV_DIR%...
if not exist "%VENV_DIR%\pyvenv.cfg" (
    echo Creating new virtual environment...
    uv venv "%VENV_DIR%" --seed
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment exists.
)

REM --- Install/Update Requirements ---
echo Installing/Updating requirements: %REQUIREMENTS%...
uv pip install %REQUIREMENTS% -p "%PYTHON_EXE%"
if %errorlevel% neq 0 (
    echo Error: Failed to install requirements. Check your internet connection or UV setup.
    pause
    exit /b 1
)

REM --- Launch the Application ---
echo Launching application...
"%PYTHON_EXE%" "%APP_DIR%main.py"
if %errorlevel% neq 0 (
    echo Error: Failed to launch main.py. Check Python script for errors.
    pause  REM <-- Ajoute une pause ici aussi en cas d'échec du lancement
    exit /b 1
)


echo Application closed or script finished.
endlocal
pause  REM <--- Assure-toi que cette ligne est présente et active