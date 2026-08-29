@echo off
chcp 65001 >nul
cls
echo ========================================
echo   ATENCION: RESET TOTAL
echo ========================================
echo.
echo Esto BORRARA TODOS LOS DATOS de Cartera
echo y volvera a ejecutar el DDL desde cero.
echo.
echo Usar solo si quieres empezar limpio.
echo.

set /p confirmacion="Escribe BORRAR ^(en mayusculas^) para confirmar: "

if not "%confirmacion%"=="BORRAR" (
    echo.
    echo Cancelado. No se borro nada.
    pause
    exit /b 0
)

echo.
echo Deteniendo container y borrando volumen...
docker compose down -v

echo.
echo Recreando todo desde cero...
docker compose up -d

echo.
echo Esperando 15 segundos a que se inicialice...
timeout /t 15 /nobreak >nul

echo.
echo [OK] Reset completado. Base de datos limpia y recreada.
pause
