"""Configuration utilisateur partagee (non personnelle).

Le nom sous lequel Jarvis s'adresse a l'utilisateur est configurable via la
variable d'environnement JARVIS_USER_NAME (definie dans .env). Valeur par
defaut neutre : "Monsieur".
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

USER_NAME = (os.getenv("JARVIS_USER_NAME") or "").strip() or "Monsieur"
