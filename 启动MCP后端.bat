@echo off
setlocal
cd /d %~dp0

set "LOG=logs\backend.log"
set "URL=http://127.0.0.1:8000"

echo ==========================================
echo  光储智联 MCP 后端启动脚本
echo  端口: 8000    MCP 入口: %URL%/mcp
echo ==========================================

if not exist logs mkdir logs

:: ---- 后端是否已在运行 ----
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%URL%/api/health' -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [OK] 后端已在运行:  %URL%
    echo      MCP 入口:      %URL%/mcp
    echo      API 文档:      %URL%/docs
    echo      自检命令:      python mcp_test.py
    if exist %LOG% goto tail
    echo.
    echo [提示] 本脚本没有它的日志文件——它是从别的窗口启动的。
    echo        要实时看日志，请先关掉那个窗口，再重新运行本脚本。
    echo.
    pause
    exit /b 0
)

:: ---- 定位 Python ----
set "PYCMD="
python --version >nul 2>&1
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto pycmd_ok
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
:pycmd_ok
if not defined PYCMD (
    echo.
    echo [Error] 未找到 Python，请安装 Python 3.12 后重试。
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('%PYCMD% --version') do echo [OK] %%v

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

:: APP_SECRET_KEY 未配置时生成随机密钥（仅本次运行有效）
if "%APP_SECRET_KEY%"=="" (
    for /f "delims=" %%k in ('powershell -NoProfile -Command "$b=New-Object byte[] 48;[Security.Cryptography.RandomNumberGenerator]::Fill($b);[Convert]::ToBase64String($b)"') do set "APP_SECRET_KEY=%%k"
    echo [OK] 已生成临时 APP_SECRET_KEY（持久配置请设置系统环境变量）
)

echo.
echo [启动] 后端进程（无窗口），日志写入 %LOG%
:: 用隐藏窗口跑后端：原来的 start "..." cmd /c ... 会多开一个窗口，
:: 而输出已重定向到日志，那个窗口必然是空的，纯占地方。
:: 辅助脚本内部用 2>&1 把 stdout/stderr 合并到同一个日志文件，
:: 这样下面只需监听一个文件（uvicorn 的 error 走 stderr、access 走 stdout）。
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0run_backend_hidden.bat' -WindowStyle Hidden"

echo 等待服务就绪...
set /a retries=0
:wait_loop
if %retries% geq 25 goto failed
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%URL%/api/health' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto tail
set /a retries+=1
ping -n 2 127.0.0.1 >nul
goto wait_loop

:failed
echo.
echo [Error] 启动失败。常见原因：
echo         1. 依赖未安装   pip install -r requirements.txt
echo         2. 8000 被占用  netstat -ano ^| findstr :8000
echo         3. 查看日志     type %LOG%
echo.
pause
exit /b 1

:tail
echo.
echo ==========================================
echo  后端就绪:  %URL%
echo  MCP 入口:  %URL%/mcp
echo  API 文档:  %URL%/docs
echo  自检命令:  python mcp_test.py
echo ==========================================
echo.
echo  实时日志监听: %LOG%
echo  按 Ctrl+C 停止监听（后端不受影响，继续运行）
echo ==========================================
echo.
powershell -NoProfile -Command "Get-Content -Path '%LOG%' -Wait -Tail 30"
echo.
echo [监听已停止] 后端仍在后台运行，重新运行本脚本可再次查看日志。
echo.
pause
exit /b 0
