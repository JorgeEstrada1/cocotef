@echo off
color 0B
echo ==========================================================
echo    INICIANDO SISTEMA DE CONTROL - TALLER DE IMPRESION 3D
echo ==========================================================
echo.
echo [1/3] Accediendo al directorio del proyecto...
cd /d "C:\Users\cocoyote\Desktop\inventario"

echo [2/3] Activando el entorno virtual (venv)...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo [ERROR] No se encontro la carpeta venv.
    pause
    exit
)

echo [3/3] Lanzando el servidor local de Flask...
echo.
echo ----------------------------------------------------------
echo    El sistema se esta ejecutando de forma local.
echo    Abriendo tu navegador en http://127.0.0.1:5000
echo ----------------------------------------------------------
echo.

start http://127.0.0.1:5000
python app.py
pause
