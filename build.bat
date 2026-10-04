@echo off
rem Builds dist\AutoClicker.exe. Run from the project folder in a normal Command Prompt.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist .venv (
    echo Creating virtual environment...
    %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo Installing dependencies...
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error

echo Building AutoClicker.exe...
pyinstaller --clean --noconfirm AutoClicker.spec || goto :error

echo.
echo Done: %cd%\dist\AutoClicker.exe
exit /b 0

:error
echo.
echo Build failed.
exit /b 1