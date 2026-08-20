@echo off
REM Duplo clique neste arquivo pra instalar — ele contorna o bloqueio padrão do Windows
REM pra rodar scripts .ps1, sem precisar mudar nenhuma configuração do sistema.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
echo.
pause
