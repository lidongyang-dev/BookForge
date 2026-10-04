@echo off
rem ================================================
rem  BookForge - Create Desktop Shortcut
rem  中文注释：本文件以 GBK 编码保存
rem  双击本文件将在桌面创建 BookForge 快捷方式，
rem  快捷方式指向当前文件夹（便携包解压位置），
rem  不包含任何绝对路径；移动文件夹后可重新双击生成
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