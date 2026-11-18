@echo off
rem Solo para compilar en tu PC. Lo normal es que lo compile GitHub Actions.
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install --upgrade -r requirements.txt pyinstaller || goto :error
py -m PyInstaller --noconfirm --clean --onefile --windowed --name Plazo --icon plazo.ico --add-data "ui;ui" --collect-all webview --collect-all clr_loader --collect-all pythonnet plazo.py || goto :error
echo Listo: dist\Plazo.exe
pause
exit /b 0
:error
echo Algo ha fallado. Copia el mensaje de arriba.
pause
exit /b 1
