@echo off
rem ================================================
rem  BookForge 启动脚本 - 自制 Kindle 书籍工作台
rem  中文注释：本文件使用 UTF-8 编码保存
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
start "" http://127.0.0.1:8777
python server.py
pause
