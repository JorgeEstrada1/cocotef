@echo off
cd /d "C:\Users\cocoyote\Desktop\gestion3d"
set BACKUP_DIR=backups
if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
set TIMESTAMP=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
copy gestion3d.db "%BACKUP_DIR%\gestion3d_%TIMESTAMP%.db" >nul
echo Backup creado: backups\gestion3d_%TIMESTAMP%.db
pause
