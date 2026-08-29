@echo off
chcp 65001 >nul
cls
echo ========================================
echo   Deteniendo PostgreSQL Cartera
echo ========================================
echo.

docker compose down

echo.
echo [OK] Base de datos detenida.
echo Los datos se conservan en el volumen Docker.
echo Para volver a levantarla: doble click en iniciar.bat
echo.
pause
