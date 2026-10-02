@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
setlocal EnableExtensions
cd /d "%~dp0"
title AvarIA

echo.
echo   AvarIA - as perdas da loja a vista
echo   ==================================
echo.

if not exist "app.py" (
  echo [ERRO] Este script precisa estar na pasta do projeto ^(onde fica o app.py^).
  echo.
  pause
  exit /b 1
)

rem --- Localiza o Python 3 -------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERRO] Python 3 nao encontrado neste computador.
  echo.
  echo   1. Baixe em https://www.python.org/downloads/
  echo   2. Na instalacao, marque "Add python.exe to PATH"
  echo   3. Depois rode este script de novo.
  echo.
  pause
  exit /b 1
)

rem --- Ambiente virtual ----------------------------------------------------
set "PRIMEIRA=0"
if not exist "venv\Scripts\python.exe" (
  set "PRIMEIRA=1"
  echo Criando o ambiente virtual...
  %PY% -m venv venv
  if errorlevel 1 (
    echo [ERRO] Nao foi possivel criar o ambiente virtual.
    echo.
    pause
    exit /b 1
  )
)

if "%PRIMEIRA%"=="1" (
  echo Instalando as dependencias ^(pode demorar alguns minutos na primeira vez^)...
  "venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
) else (
  echo Conferindo as dependencias...
  "venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao instalar as dependencias.
  echo Verifique a conexao com a internet e tente novamente.
  echo.
  pause
  exit /b 1
)

echo.
echo Iniciando o sistema em http://localhost:5000 ...
if not defined AVARIA_SEM_BROWSER (
  start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:5000'"
)

echo.
echo   O navegador vai abrir sozinho. Se nao abrir, acesse:
echo   http://localhost:5000
echo.
echo   Para encerrar: feche esta janela ou pressione Ctrl+C.
echo.

"venv\Scripts\python.exe" app.py
echo.
echo O sistema foi encerrado.
pause
