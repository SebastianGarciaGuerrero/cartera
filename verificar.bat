@echo off
chcp 65001 >nul
cls
echo ========================================
echo   Estado del container PostgreSQL de Cartera
echo ========================================
echo.

docker ps --filter "name=cartera-postgres" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo ========================================
echo   Ultimos 30 logs
echo ========================================
docker compose logs --tail 30 postgres

echo.
echo ========================================
echo   Verificacion rapida de tablas
echo ========================================
docker exec cartera-postgres psql -U cartera_admin -d cartera -c "SELECT count(*) AS total_tablas FROM information_schema.tables WHERE table_schema = 'public';"

echo.
pause
