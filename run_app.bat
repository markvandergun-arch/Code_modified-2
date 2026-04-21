@echo off
setlocal

REM --- Always run from this .bat location (project root) ---
cd /d "%~dp0"

REM --- Configure venv folder name (change if needed) ---
set "VENV_DIR=.venv"

REM --- Activate venv if it exists ---
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
) else (
    echo [ERROR] Virtual environment not found: "%VENV_DIR%"
    echo Create one with:
    echo   python -m venv %VENV_DIR%
    echo Then install requirements:
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM --- Ensure streamlit is installed ---
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing streamlit...
    pip install streamlit
)

REM --- Run the app ---
echo [INFO] Starting Streamlit app...
streamlit run app.py

endlocal