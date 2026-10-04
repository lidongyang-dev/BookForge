@echo off
rem ================================================
rem  BookForge - Create Desktop Shortcut
rem  Run this once after unzipping: it creates a
rem  BookForge shortcut on your desktop that points
rem  to THIS folder (no hard-coded absolute path).
rem  Re-run it if you move the folder to a new place.
rem ================================================
cd /d "%~dp0"
title BookForge - Create Desktop Shortcut
echo.
echo  ================================================
echo   Creating BookForge shortcut on your desktop...
echo   Target folder: %~dp0
echo  ================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\BookForge.lnk');" ^
  "$s.TargetPath='%~dp0runtime\pythonw.exe';" ^
  "$s.Arguments='server.py --desktop';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%~dp0BookForge.ico';" ^
  "$s.Description='BookForge - Kindle Book Maker';" ^
  "$s.Save()"
if %errorlevel%==0 (
  echo  Done. BookForge.lnk created on your desktop.
) else (
  echo  Failed. Make sure runtime\pythonw.exe exists in this folder.
)
echo.
pause