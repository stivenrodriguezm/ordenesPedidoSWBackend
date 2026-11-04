@echo off
rem Instala el agente de impresion de Lottus en este Windows (sin permisos de administrador).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause
