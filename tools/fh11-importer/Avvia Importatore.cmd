@echo off
setlocal
if exist "%~dp0Portable\FreeHandImporter.exe" goto portable
if exist "%~dp0FreeHandImporter.exe" goto portable_here
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto share_error
python -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 goto python
py -3 -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 goto py
echo Python 3.10 o successivo con Tkinter non trovato su questo PC.
echo Usa la versione Portable, che include Python, oppure installa Python.
echo Copiare la cartella di rete non installa Python sul computer.
pause
popd
exit /b 1
:python
python "%~dp0launch.py" %*
goto done
:py
py -3 "%~dp0launch.py" %*
:done
if errorlevel 1 pause
popd
exit /b
:portable
start "" "%~dp0Portable\FreeHandImporter.exe" %*
exit /b
:portable_here
start "" "%~dp0FreeHandImporter.exe" %*
exit /b
:share_error
echo Impossibile accedere alla cartella dell'importatore.
echo Controlla il collegamento di rete e i permessi della condivisione.
pause
exit /b 1
