@echo off
REM Compile l'installateur Windows JarvisSetup-<version>.exe (Inno Setup 6).
REM Prerequis :
REM   1. Inno Setup 6 installe (winget install JRSoftware.InnoSetup)
REM   2. Les .exe a jour a la racine du repo (lance build_all.bat d'abord)
REM Sortie : installer\output\JarvisSetup-<version>.exe
REM La version est lue dans jarvis_version.py (source de verite unique).

setlocal
cd /d "%~dp0.."

if not exist Jarvis.exe (
  echo Jarvis.exe manquant a la racine : lance build_all.bat d'abord.
  exit /b 1
)

REM Localise ISCC.exe (installation standard puis PATH)
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  where ISCC.exe >nul 2>nul || (
    echo Inno Setup introuvable : winget install JRSoftware.InnoSetup
    exit /b 1
  )
  set "ISCC=ISCC.exe"
)

REM Extrait x.y.z de la ligne : VERSION = "x.y.z"
set "VERSION="
for /f tokens^=2^ delims^=^" %%v in ('findstr /B /C:"VERSION = " jarvis_version.py') do set "VERSION=%%v"
if "%VERSION%"=="" (
  echo Impossible de lire VERSION dans jarvis_version.py
  exit /b 1
)

REM Compile dans %TEMP% puis copie : ecrire le Setup.exe directement dans un
REM dossier utilisateur surveille (Desktop...) fait echouer EndUpdateResource
REM (Defender verrouille le binaire pendant la mise a jour des ressources).
set "OUTTMP=%TEMP%\jarvis_installer_out"

echo === Compilation de JarvisSetup-%VERSION%.exe ===
"%ISCC%" /DAppVersion=%VERSION% /O"%OUTTMP%" installer\JarvisSetup.iss
if errorlevel 1 (
  echo ECHEC de la compilation de l'installateur.
  exit /b 1
)

if not exist installer\output mkdir installer\output
copy /Y "%OUTTMP%\JarvisSetup-%VERSION%.exe" "installer\output\JarvisSetup-%VERSION%.exe" >nul

echo.
echo === DONE : installer\output\JarvisSetup-%VERSION%.exe ===
endlocal
