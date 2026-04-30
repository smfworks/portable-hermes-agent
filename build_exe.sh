#!/usr/bin/env bash
# build_exe.sh — Build SMF Forge Desktop single-file GUI executable
# Run this from the project root.
# Cross-platform (Linux / macOS) for dry-run validation.
# Windows users should prefer build_exe.bat (PowerShell/cmd).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

PYTHON="${PYTHON:-python3}"

echo "=== SMF Forge Desktop Build Script ==="
echo "Python: $PYTHON"
echo ""

# ---------------------------------------------------------------------------
# 1. Verify environment
# ---------------------------------------------------------------------------
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: Python not found: $PYTHON"
    exit 1
fi

PY_VER=$($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Python version: $PY_VER"

if ! $PYTHON -c "import tkinter" 2>/dev/null; then
    echo "WARNING: tkinter not detected in this Python. Install python3-tk (Debian/Ubuntu) or python-tk (Arch/Fedora)."
    echo "PyInstaller may still build the exe, but the runtime will need tk/Tcl bundled."
fi

# ---------------------------------------------------------------------------
# 2. Install / upgrade build deps
# ---------------------------------------------------------------------------
echo "Installing/upgrading build dependencies..."
$PYTHON -m pip install --upgrade pip setuptools wheel
$PYTHON -m pip install --upgrade pyinstaller>=6.0

# ---------------------------------------------------------------------------
# 3. Clean previous build
# ---------------------------------------------------------------------------
echo "Cleaning old build artifacts..."
rm -rf build dist *.egg-info .pytest_cache .mypy_cache

# ---------------------------------------------------------------------------
# 4. Run PyInstaller analysis (dry-run mode if available)
# ---------------------------------------------------------------------------
# PyInstaller doesn't have a pure dry-run, but we can run it and let it fail
# on missing deps. On Linux this won't produce a Windows .exe natively,
# but it validates the .spec file and hiddenimports.
echo ""
echo "Running PyInstaller in ANALYSIS-ONLY mode..."
echo "(On Linux this validates the spec but creates a Linux ELF, not Windows .exe)"
echo ""

set +e
$PYTHON -m PyInstaller smf-forge-desktop.spec \
    --clean \
    --noconfirm \
    --log-level WARN

EXIT_CODE=$?
set -e

# ---------------------------------------------------------------------------
# 5. Report
# ---------------------------------------------------------------------------
if [ -f "dist/smf-forge-desktop" ] || [ -f "dist/smf-forge-desktop.exe" ]; then
    echo ""
    echo "========================================="
    echo "Build artifact present:"
    ls -lh dist/smf-forge-desktop* | head -n 5
    echo ""
    echo "NOTE: If you see 'smf-forge-desktop' (ELF) you're on Linux."
    echo "      To produce a real Windows .exe, run this script on Windows with build_exe.bat"
    echo "      or use cross-compilation (e.g. mingw-w64 + wine)."
    echo "========================================="
fi

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "ERROR: PyInstaller exited with code $EXIT_CODE"
    echo "Check the output above for missing imports or data files."
    exit $EXIT_CODE
fi

echo ""
echo "Build validation passed."
