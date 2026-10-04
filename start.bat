@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BookForge - 自制 Kindle 书籍工作台
echo.
echo  ================================================
echo   BookForge 启动中...
echo   启动后浏览器将自动打开 http://127.0.0.1:8777
echo   关闭本窗口即停止服务
echo  ================================================
echo.
start "" http://127.0.0.1:8777
python server.py
pause
