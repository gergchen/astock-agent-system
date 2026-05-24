@echo off
chcp 65001 >nul
cd /d "%~dp0"

if "%1"=="stop" (
    echo 停止飞书 Bot...
    wmic process where "commandline like '%%managed_agents.main feishu%%'" delete >nul 2>&1
    timeout /t 2 /nobreak >nul
    del /f /q "%TEMP%\feishu_bot.pid" 2>nul
    echo Bot 已停止
    exit /b
)

if "%1"=="status" (
    wmic process where "commandline like '%%managed_agents.main feishu%%'" get processid,commandline 2>nul | findstr "python"
    if errorlevel 1 (
        echo Bot 未运行
    )
    exit /b
)

echo 启动飞书 Bot...
start /B python -m managed_agents.main feishu > "%TEMP%\feishu_bot.log" 2>&1
timeout /t 3 /nobreak >nul
wmic process where "commandline like '%%managed_agents.main feishu%%'" get processid 2>nul | findstr /r "^[0-9]"
echo Bot 已启动
