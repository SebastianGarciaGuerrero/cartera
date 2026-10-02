@echo off
chcp 65001 >nul
cls
echo ========================================
echo   CARTERA - Iniciando base de datos
echo ========================================
echo.

REM Verificar que Docker esta corriendo
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no esta instalado o no esta corriendo.
    echo.
    echo Soluciones:
    echo   1. Abre Docker Desktop ^(busca en el menu inicio^)
    echo   2. Espera a que el icono de la ballena este verde
    echo   3. Vuelve a ejecutar este script
    echo.
    pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop esta instalado pero no esta corriendo.
    echo Abre Docker Desktop y espera a que aparezca "Engine running".
    echo.
    pause
    exit /b 1
)

echo [OK] Docker esta corriendo
echo.
echo Levantando PostgreSQL 16 ^(puerto 5433^)...
echo La primera vez tarda 2-3 minutos descargando la imagen.
echo.

docker compose up -d

if errorlevel 1 (
    echo.
    echo [ERROR] Algo fallo al levantar el container.
    echo Revisa los mensajes de arriba.
    pause
    exit /b 1
)

echo.
echo Esperando 15 segundos a que PostgreSQL se inicialice...
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
echo ========================================
echo   Estado del container
echo ========================================
docker ps --filter "name=cartera-postgres" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo ========================================
echo   LISTO - PostgreSQL corriendo
echo ========================================
echo.
echo Datos de conexion para DBeaver:
echo.
echo   Host:     localhost
echo   Port:     5433
echo   Database: cartera
echo   User:     cartera_admin
echo   Password: desarrollo_local_2026
echo.
echo Para ver los logs: ejecuta verificar.bat
echo Para detener:      ejecuta detener.bat
echo.
pause
