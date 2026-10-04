@echo off
rem ================================================
rem  BookForge 启动脚本 - 自制 Kindle 书籍工作台
rem  中文注释：本文件使用 UTF-8 编码保存
rem  优先使用项目内便携运行时 runtime\python.exe，
rem  不存在时回退到系统 PATH 中的 python
rem ================================================
cd /d "%~dp0"
title BookForge - Kindle Book Maker
echo.
echo  ================================================
echo   BookForge is starting...
echo   The browser will open http://127.0.0.1:8777 automatically
echo   Close this window to stop the service
echo  ================================================
echo.
if exist "runtime\python.exe" (
  set "PY=runtime\python.exe"
) else (
  set "PY=python"
)
start "" http://127.0.0.1:8777
"%PY%" server.py
pause
