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

echo === Copie des binaires a la racine ===
REM Builds ONEDIR : Jarvis et JarvisWeb sont des DOSSIERS (exe + _internal*),
REM pas des fichiers uniques. On copie leur contenu a la racine pour garder le
REM double-clic direct : Jarvis.exe + _internal\ et JarvisWeb.exe + _internal_web\
REM cohabitent (dossiers de contenu distincts), et partagent .env / memoire au
REM meme endroit. ModelAdvisor reste un onefile (tkinter stdlib, FP negligeable).
xcopy "dist\Jarvis" "." /E /Y /I /Q
xcopy "dist\JarvisWeb" "." /E /Y /I /Q
copy /Y model_advisor\dist\ModelAdvisor.exe ModelAdvisor.exe

echo.
echo === DONE ===
dir /B *.exe
endlocal
