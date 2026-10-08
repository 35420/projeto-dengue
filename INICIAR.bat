@echo off
setlocal EnableExtensions
cd /d "%~dp0"

cls
echo ================================================
echo       PROJETO DENGUE - FRANCA / SP
echo ================================================
echo.

set "PYTHON=python"
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [ERRO] Python nao foi encontrado no PATH.
        echo Instale o Python e marque "Add Python to PATH".
        pause
        exit /b 1
    ) else (
        set "PYTHON=py"
    )
)

echo [1/4] Versao do Python detectada:
%PYTHON% --version
echo.

echo [2/4] Verificando/Criando Ambiente Virtual (venv)...
if not exist "venv" (
    echo Criando ambiente virtual...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel criar o ambiente virtual.
        pause
        exit /b 1
    )
)

set "VENV_PYTHON=venv\Scripts\python.exe"

echo [3/4] Atualizando pip e instalando dependencias...
"%VENV_PYTHON%" -m pip install --upgrade pip >nul 2>&1
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias no ambiente virtual.
    pause
    exit /b 1
)

echo.
echo [4/4] Iniciando o servidor Flask no Python atualizado...
echo.
echo Endereco: http://127.0.0.1:5000
echo Nao feche esta janela enquanto utilizar o sistema.
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:5000"
"%VENV_PYTHON%" -u app.py

pause
endlocal