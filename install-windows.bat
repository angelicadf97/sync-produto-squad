@echo off
REM Duplo clique neste arquivo para instalar - ele contorna o bloqueio padrao do Windows
REM para rodar scripts .ps1, sem precisar mudar nenhuma configuracao do sistema.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
echo.
pause
