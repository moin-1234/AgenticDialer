@echo off
setlocal ENABLEDELAYEDEXPANSION

rem Ensure commands run relative to this script
pushd "%~dp0"

echo Starting AI Calling Agent - Full Stack...
echo.

echo ============================================
echo Starting Backend (FastAPI)...
echo ============================================
start "Backend" cmd /c "%~dp0start-backend.bat"

echo Waiting for backend to initialize...
timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo Starting Frontend (React + Vite)...
echo ============================================
start "Frontend" cmd /c "%~dp0start-frontend.bat"

echo.
echo ============================================
echo Both services are starting...
echo ============================================
echo.
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000
echo API Docs: http://localhost:8000/docs
echo.
echo Press any key to stop all services...
pause >nul

echo.
echo Stopping services...
rem Attempt graceful shutdown before forcing
for %%P in (python.exe pythonw.exe node.exe) do (
    taskkill /f /im "%%P" >nul 2>&1
)

echo Services stopped.

popd
endlocal
pause
