@echo off
rem ================================================
rem  BookForge 启动脚本 - 自制 Kindle 书籍工作台
rem  中文注释：本文件使用 UTF-8 编码保存
rem  默认以桌面窗口模式启动（pywebview 原生窗口），
rem  优先使用项目内便携运行时 runtime\python.exe，
rem  不存在时回退到系统 PATH 中的 python
rem  如需纯服务模式（浏览器访问），命令行执行: python server.py
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
