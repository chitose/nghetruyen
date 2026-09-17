:: app/build.bat
:: Builds the standalone NgheTruyen.exe (see README.md's "Standalone
:: NgheTruyen.exe" section). Needs app/venv already set up -- run.bat does
:: that on first launch.
@echo off
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo venv not found -- run run.bat first to set it up.
    exit /b 1
)

venv\Scripts\python.exe -m pip install pyinstaller || exit /b 1
venv\Scripts\python.exe -m PyInstaller --noconfirm NgheTruyen.spec || exit /b 1

copy /y dist\NgheTruyen.exe . >nul
if errorlevel 1 (
    echo Could not overwrite NgheTruyen.exe -- close it if it is running and copy dist\NgheTruyen.exe here by hand.
    exit /b 1
)

echo Built NgheTruyen.exe.
