@echo off
rem ================================================
rem  BookForge launcher - Kindle Book Maker
rem  Default mode: desktop window (pywebview native)
rem  Uses portable runtime\python.exe first,
rem  falls back to python on PATH.
rem  Pure service mode (browser): python server.py
rem ================================================
cd /d "%~dp0"
title BookForge - Kindle Book Maker
echo.
echo  ================================================
echo   BookForge is starting...
echo   A desktop window will open automatically
echo   Close the window to stop the service
echo  ================================================
echo.
if exist "runtime\python.exe" (
  set "PY=runtime\python.exe"
) else (
  set "PY=python"
)
"%PY%" server.py --desktop %*
pause