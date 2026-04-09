@echo off
cd /d "%~dp0"

REM --- Support distribution layout (_internal/) ---
if exist "_internal" cd _internal

REM --- Check for ffmpeg ---
where ffmpeg >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: ffmpeg is not installed!
    echo.
    echo Install it with one of these methods:
    echo   - winget install Gyan.FFmpeg
    echo   - choco install ffmpeg
    echo   - Download from https://ffmpeg.org
    pause
    exit /b
)

REM --- Check for uv ---
where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Initializing environment ^(installing uv^)...
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Starting Gather...
uv run --with fastapi --with uvicorn --with python-multipart --with jinja2 --with Pillow --with pytz --with pywebview main.py
echo Gather has closed.
pause
