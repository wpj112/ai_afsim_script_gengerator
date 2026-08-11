@echo off
setlocal

rem ============================================================
rem AFSIM Windows Runner
rem Edit the values below, then double-click this file.
rem Keep this file ASCII-only to avoid Windows CMD encoding issues.
rem ============================================================

set "AFSIM_INSTALL_DIR=D:\Program Files\afsim2.9.0"
set "MISSION_EXE=%AFSIM_INSTALL_DIR%\bin\mission.exe"
set "RUNNER_HOST=0.0.0.0"
set "RUNNER_PORT=9001"
set "RUNNER_WORKSPACES=D:\afsim-runner\workspaces"

rem If python is not in PATH, set a full path here.
rem Example:
rem set "PYTHON_EXE=C:\Users\you\AppData\Local\Programs\Python\Python313\python.exe"
set "PYTHON_EXE=python"

rem ============================================================
rem Do not edit below unless you know what you are doing.
rem ============================================================

set "BAT_DIR=%~dp0"
set "PROJECT_DIR=%BAT_DIR%.."
set "RUNNER_SCRIPT=%BAT_DIR%windows_runner.py"

if not exist "%RUNNER_SCRIPT%" (
  set "RUNNER_SCRIPT=%PROJECT_DIR%\scripts\windows_runner.py"
)

if not exist "%RUNNER_SCRIPT%" (
  echo [ERROR] windows_runner.py not found.
  echo Expected one of:
  echo   "%BAT_DIR%windows_runner.py"
  echo   "%PROJECT_DIR%\scripts\windows_runner.py"
  echo.
  echo Keep start_windows_runner.bat and windows_runner.py in the scripts folder,
  echo or run the bat from the project copied with its scripts folder.
  pause
  exit /b 1
)

cd /d "%PROJECT_DIR%"
if errorlevel 1 (
  echo [ERROR] Failed to enter project directory.
  pause
  exit /b 1
)

if "%MISSION_EXE%"=="" (
  echo [ERROR] MISSION_EXE is empty.
  echo Edit scripts\start_windows_runner.bat and set MISSION_EXE.
  pause
  exit /b 1
)

if not exist "%MISSION_EXE%" (
  echo [ERROR] mission.exe not found:
  echo "%MISSION_EXE%"
  echo.
  echo Edit scripts\start_windows_runner.bat and set AFSIM_INSTALL_DIR or MISSION_EXE.
  pause
  exit /b 1
)

if not exist "%RUNNER_WORKSPACES%" (
  mkdir "%RUNNER_WORKSPACES%"
  if errorlevel 1 (
    echo [ERROR] Failed to create RUNNER_WORKSPACES:
    echo "%RUNNER_WORKSPACES%"
    pause
    exit /b 1
  )
)

echo ============================================================
echo AFSIM Windows Runner
echo ============================================================
echo Mission:    "%MISSION_EXE%"
echo Workspaces: "%RUNNER_WORKSPACES%"
echo Listen:     http://%RUNNER_HOST%:%RUNNER_PORT%
echo Health:     http://localhost:%RUNNER_PORT%/healthz
echo.
echo Linux config:
echo   EXECUTOR_MODE=remote
echo   AFSIM_RUNNER_URL=http://WINDOWS_IP:%RUNNER_PORT%
echo ============================================================
echo.

"%PYTHON_EXE%" "%RUNNER_SCRIPT%" ^
  --host "%RUNNER_HOST%" ^
  --port "%RUNNER_PORT%" ^
  --mission-exe "%MISSION_EXE%" ^
  --workspaces-dir "%RUNNER_WORKSPACES%"

echo.
echo Runner stopped.
pause
