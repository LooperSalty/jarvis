"""Configuration utilisateur partagee (non personnelle).

Le nom sous lequel Jarvis s'adresse a l'utilisateur est configurable via la
variable d'environnement JARVIS_USER_NAME (definie dans .env). Valeur par
defaut neutre : "Monsieur".
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    if getattr(sys, "frozen", False):
        # Mode .exe : le .env persistant vit A COTE du binaire (meme pattern
        # que _dossier_donnees). Le cwd etant sys._MEIPASS (temporaire),
        # load_dotenv() sans chemin ne le trouverait jamais — et ce module est
        # souvent importe AVANT que main2 ne charge le .env persistant : il
        # doit donc le charger lui-meme (premier lu gagne, pas d'ecrasement).
        load_dotenv(Path(sys.executable).resolve().parent / ".env")
    load_dotenv()
except Exception:
    pass

USER_NAME = (os.getenv("JARVIS_USER_NAME") or "").strip() or "Monsieur"
