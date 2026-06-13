@echo off
REM ============================================================================
REM jcode - ouvre une session de code Claude Code (tous les outils) dans un
REM dossier, depuis un terminal. Complement de Jarvis (le CLI "jarvis" est pris
REM par le package OpenJarvis, on utilise donc "jcode").
REM
REM Usage :
REM   jcode             Session interactive dans le dossier courant
REM   jcode <chemin>    Session interactive dans ce dossier
REM   jcode <prompt>    Passe le prompt / les options directement a Claude Code
REM ============================================================================
setlocal
where claude >nul 2>nul
if errorlevel 1 (
  echo [jcode] Claude Code introuvable dans le PATH.
  echo         Installe-le : https://claude.com/claude-code
  exit /b 1
)

if "%~1"=="" (
  echo [jcode] Session de code Claude Code dans : %CD%
  claude
) else if exist "%~1\" (
  echo [jcode] Session de code Claude Code dans : %~f1
  pushd "%~1"
  claude
  popd
) else (
  claude %*
)
endlocal
