@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  python -m venv .venv || goto :error
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

echo.
echo Iniciando YEDTradingBot en http://127.0.0.1:8765
echo.
".venv\Scripts\python.exe" run.py
goto :eof

:error
echo.
echo No se pudo iniciar. Revisa que Python 3.11+ este instalado y en el PATH.
pause
