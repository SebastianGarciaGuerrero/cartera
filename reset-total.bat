@echo off
chcp 65001 >nul
cls
echo ========================================
echo   ATENCION: RESET TOTAL
echo ========================================
echo.
echo Esto BORRARA TODOS LOS DATOS de Cartera
echo y volvera a crear el esquema desde cero.
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
echo Aplicando migraciones de la base de datos...
pushd backend
.venv\Scripts\alembic.exe upgrade head
if errorlevel 1 (
    echo [ERROR] Fallaron las migraciones. Revisa backend\.env ^(DATABASE_URL^).
    popd
    pause
    exit /b 1
)
popd

echo.
echo [OK] Reset completado. Base de datos limpia y recreada.
echo Crea tu organizacion con: python -m app.cli crear-organizacion ...
pause
