@echo off
setlocal

REM --- Configuration ---
set APP_DIR=%~dp0
set VENV_NAME=.venv_dist
set VENV_DIR=%APP_DIR%%VENV_NAME%
set PYTHON_EXE=%VENV_DIR%\Scripts\python.exe
set REQUIREMENTS_FILE=%APP_DIR%requirements.txt
set MAIN_SCRIPT=%APP_DIR%main.py

echo --- Pythautom Project Runner (Windows) ---
echo Project Directory: %APP_DIR%

REM --- Check for Python ---
echo Checking for Python...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not found in PATH. Please install Python 3.11+ and add it to PATH.
    goto :error_exit
) else (
    echo Found Python.
)

REM --- Check/Install UV ---
echo Ensuring UV is available (installing/upgrading)...
python -m pip install --user --upgrade uv
if %errorlevel% neq 0 (
    echo Error: Failed to install or upgrade UV using pip. Check internet connection and pip setup.
    echo Please try installing manually: python -m pip install uv
    goto :error_exit
)

REM --- Verify UV Installation ---
echo Verifying UV installation...
uv --version > nul 2>&1
if %errorlevel% neq 0 (
     echo Error: UV command still not found after installation attempt.
     echo Please check your system's PATH environment variable or try installing manually again.
     goto :error_exit
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
        goto :error_exit
    )
) else (
    echo Virtual environment exists. Checking Python version...
    REM Optional: Add check if existing venv python matches required version
)

REM --- Check for requirements.txt ---
if not exist "%REQUIREMENTS_FILE%" (
    echo Error: requirements.txt not found in %APP_DIR%. Cannot install dependencies.
    goto :error_exit
)

REM --- Install/Update Requirements ---
echo Installing requirements from %REQUIREMENTS_FILE%...
uv pip install -r "%REQUIREMENTS_FILE%" -p "%PYTHON_EXE%"
if %errorlevel% neq 0 (
    echo Error: Failed to install requirements using uv. Check the requirements file and internet connection.
    goto :error_exit
)
echo Requirements installed successfully.

REM --- Check for main script ---
if not exist "%MAIN_SCRIPT%" (
    echo Error: %MAIN_SCRIPT% not found. Cannot run the application.
    goto :error_exit
)

REM --- Launch the Application ---
echo Launching application...
"%PYTHON_EXE%" "%MAIN_SCRIPT%"
if %errorlevel% neq 0 (
    echo Error: Failed to launch %MAIN_SCRIPT%. Check Python script for errors.
    goto :error_exit
)

echo Application closed or script finished successfully.
goto :end

:error_exit
echo.
echo An error occurred. Please check the messages above.
pause
exit /b 1

:end
echo.
echo Script finished.
endlocal
pause