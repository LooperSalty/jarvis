@echo off
REM Build des 3 .exe + copie a la racine du projet pour acces direct.
REM Lance depuis la racine : .\build_all.bat

setlocal
cd /d "%~dp0"

echo === [1/4] Build du frontend (Vite production) ===
pushd frontend
call npx vite build
popd
if errorlevel 1 ( echo ECHEC build frontend & exit /b 1 )

echo === [2/4] Build Jarvis.exe (desktop arriere-plan, Qt+WebEngine) ===
python -m PyInstaller Jarvis.spec --clean --noconfirm
if errorlevel 1 ( echo ECHEC build Jarvis.exe & exit /b 1 )

echo === [3/4] Build JarvisWeb.exe (backend + browser) ===
python -m PyInstaller JarvisWeb.spec --clean --noconfirm
if errorlevel 1 ( echo ECHEC build JarvisWeb.exe & exit /b 1 )

echo === [4/4] Build ModelAdvisor.exe (Tkinter) ===
pushd model_advisor
python -m PyInstaller --onefile --windowed --name ModelAdvisor --clean --noconfirm model_advisor.py
popd
if errorlevel 1 ( echo ECHEC build ModelAdvisor.exe & exit /b 1 )

echo === Copie des .exe a la racine ===
copy /Y dist\Jarvis.exe Jarvis.exe
copy /Y dist\JarvisWeb.exe JarvisWeb.exe
copy /Y model_advisor\dist\ModelAdvisor.exe ModelAdvisor.exe

echo.
echo === DONE ===
dir /B *.exe
endlocal
