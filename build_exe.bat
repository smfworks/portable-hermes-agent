@echo off
REM build_exe.bat — Build SMF Forge Desktop single-file GUI executable
REM Run this from the project root on Windows with the dev venv activated.

cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ and ensure it is on PATH.
    pause
    exit /b 1
)

for /f "tokens=*" %%a in ('python -c "import sys; print(sys.executable)"') do set "PYTHON=%%a"
echo Using Python: %PYTHON%

REM Ensure dev dependencies
if not exist "venv\Scripts\pyinstaller.exe" (
    echo Installing dev dependencies...
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install ".[dev]"
)

REM Ensure UPX for aggressive compression (auto-skip if absent)
REM Windows users can download upx.exe and place it next to this script.

set "UPX_DIR="
if exist "upx.exe"     set "UPX_DIR=%CD%"
if exist "tools\upx\upx.exe" set "UPX_DIR=%CD%\tools\upx"

REM Clean previous build
echo Cleaning old build artifacts...
if exist build\   rmdir /s /q build
if exist dist\    rmdir /s /q dist
timeout /t 1 >nul

REM Run PyInstaller
set "PYI_ARGS="
if defined UPX_DIR set "PYI_ARGS=--upx-dir %UPX_DIR%"

echo Building smf-forge-desktop.exe...
venv\Scripts\pyinstaller.exe %PYI_ARGS% smf-forge-desktop.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED ^(see above for details^)
    pause
    exit /b 1
)

echo.
echo =========================================
echo Build complete: dist\smf-forge-desktop.exe
dir "dist\smf-forge-desktop.exe" 2>nul
echo =========================================
pause
