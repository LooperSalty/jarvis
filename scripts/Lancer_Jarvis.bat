@echo off
REM Lance Jarvis en arriere-plan avec icone tray, sans fenetre console.
cd /d "%~dp0"
start "" /min pythonw.exe "jarvis_tray.py"
exit
