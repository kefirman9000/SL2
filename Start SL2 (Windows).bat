@echo off
rem Start SL2 on Windows from a download / clone of the source (the installer needs none of this).
rem First start: makes a private Python environment in %%LOCALAPPDATA%%\SL2 and installs numpy + scipy into it.
setlocal
cd /d "%~dp0"
title SL2
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :check
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
:check
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython
set "VENV=%LOCALAPPDATA%\SL2\venv"
if exist "%VENV%\Scripts\python.exe" goto :deps
echo First start: setting up SL2 - this takes a minute or two ...
%PY% -m venv "%VENV%"
if errorlevel 1 goto :fail
:deps
"%VENV%\Scripts\python.exe" -c "import numpy, scipy" >nul 2>nul
if not errorlevel 1 goto :run
echo Installing numpy and scipy ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q "numpy>=1.22" "scipy>=1.8"
if errorlevel 1 goto :fail
rem its own window (Edge WebView2); without it SL2 opens in your browser
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q "pywebview>=5.1"
:run
"%VENV%\Scripts\python.exe" sl2.py --window %*
if errorlevel 1 pause
exit /b 0
:nopython
echo.
echo SL2 needs Python 3.9 or newer.
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" while installing,
echo or download the ready-made installer from https://github.com/kefirman9000/SL2/releases
echo.
pause
exit /b 1
:fail
echo.
echo Setting up SL2 failed - check your internet connection and run this file again.
echo To start over, delete the folder %LOCALAPPDATA%\SL2
pause
exit /b 1
