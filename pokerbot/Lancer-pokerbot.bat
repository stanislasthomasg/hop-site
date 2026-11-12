@echo off
rem Double-cliquer sur ce fichier (Windows).
rem Premier lancement : cree l'environnement Python et installe le bot (1 a 2 minutes).
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python est introuvable. Installez Python 3.10+ depuis https://www.python.org
  echo en cochant "Add Python to PATH", puis relancez.
  pause
  exit /b 1
)
if not exist .venv (
  echo Premiere installation...
  python -m venv .venv || (echo Impossible de creer l'environnement Python. & pause & exit /b 1)
  .venv\Scripts\pip install -q -e . || (echo L'installation a echoue. & pause & exit /b 1)
  .venv\Scripts\pip install -q eval7 2>nul || echo eval7 non installe : le bot sera un peu plus lent.
)
echo Pokerbot demarre : la page va s'ouvrir dans votre navigateur. Fermez cette fenetre pour arreter.
.venv\Scripts\python -m pokerbot web --open
pause
