@echo off
REM Build des 3 .exe + copie a la racine du projet pour acces direct.
REM Lance depuis la racine : .\build_all.bat

setlocal
cd /d "%~dp0"

echo === [1/5] Build du frontend (Vite production) ===
pushd frontend
call npx vite build
popd
if errorlevel 1 ( echo ECHEC build frontend & exit /b 1 )

echo === [2/5] Build Jarvis.exe (desktop arriere-plan, Qt+WebEngine) ===
python -m PyInstaller Jarvis.spec --clean --noconfirm
if errorlevel 1 ( echo ECHEC build Jarvis.exe & exit /b 1 )

echo === [3/5] Build JarvisWeb.exe (backend + browser) ===
python -m PyInstaller JarvisWeb.spec --clean --noconfirm
if errorlevel 1 ( echo ECHEC build JarvisWeb.exe & exit /b 1 )

echo === [4/5] Build ModelAdvisor.exe (Tkinter) ===
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

echo === [5/5] Build du shell Tauri (optionnel : ignore si Rust/cargo absent) ===
where cargo >nul 2>&1
if errorlevel 1 (
  echo Rust/cargo absent : shell Tauri ignore. Voir jarvis-tauri\README.md.
) else (
  pushd jarvis-tauri\src-tauri
  cargo build --release
  popd
  REM JarvisTauri.exe doit cohabiter avec JarvisWeb.exe a la racine : il le lance
  REM comme backend ^(JARVIS_EXTERNAL_SHELL^) et affiche l'interface en WebView2.
  if exist "jarvis-tauri\src-tauri\target\release\jarvis-tauri.exe" (
    copy /Y "jarvis-tauri\src-tauri\target\release\jarvis-tauri.exe" JarvisTauri.exe
  ) else (
    echo ECHEC build shell Tauri ^(non bloquant^).
  )
)

echo.
echo === DONE ===
dir /B *.exe
endlocal
