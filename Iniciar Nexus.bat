@echo off
chcp 65001 >nul
title Nexus - Certificados de Bomberos
cd /d "%~dp0"
where py >nul 2>nul && goto :py
where python >nul 2>nul && goto :python
echo.
echo   No se encontro Python. Instalalo desde https://www.python.org/downloads/
echo   (marca la casilla "Add python.exe to PATH" durante la instalacion)
echo.
pause
exit /b 1
:py
py -3 nexus.py %*
goto :fin
:python
python nexus.py %*
:fin
if errorlevel 1 pause
