#!/bin/bash
# Double-cliquer (Mac) ou lancer avec ./Lancer-pokerbot.command (Linux).
# Premier lancement : crée l'environnement Python et installe le bot (1 à 2 minutes).
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python est introuvable. Installez Python 3.10 ou plus récent depuis https://www.python.org puis relancez."
  read -r -p "Appuyez sur Entrée pour fermer." _
  exit 1
fi
if [ ! -d .venv ]; then
  echo "Première installation…"
  "$PY" -m venv .venv || { echo "Impossible de créer l'environnement Python."; read -r _; exit 1; }
  .venv/bin/pip install -q -e . || { echo "L'installation a échoué (voir le message ci-dessus)."; read -r _; exit 1; }
  .venv/bin/pip install -q eval7 2>/dev/null || echo "(eval7 non installé : le bot sera un peu plus lent, ça marche quand même)"
fi
echo "Autopilote : le bot s'entraîne et s'évalue en continu ; la table s'ouvre dans le navigateur. Fermez cette fenêtre pour arrêter (il reprendra au prochain lancement)."
.venv/bin/python -m pokerbot autopilot
