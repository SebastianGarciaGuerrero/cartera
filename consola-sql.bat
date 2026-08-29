@echo off
chcp 65001 >nul
cls
echo ========================================
echo   Consola SQL - Cartera
echo ========================================
echo.
echo Estas dentro de PostgreSQL.
echo Comandos utiles:
echo   \dt              Listar todas las tablas
echo   \d nombre_tabla  Ver estructura de una tabla
echo   \q               Salir
echo.


docker exec -it cartera-postgres psql -U cartera_admin -d cartera
