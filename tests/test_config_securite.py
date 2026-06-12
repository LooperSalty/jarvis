"""Tests de jarvis_config (chargement .env en mode .exe) et du durcissement ACL.

jarvis_config est importe tres tot par main2 et tous les modules jarvis_actions :
en mode PyInstaller il doit charger lui-meme le .env persistant a cote de l'exe
(le cwd est sys._MEIPASS, load_dotenv() sans chemin ne le trouverait jamais),
sans dependre de l'ordre d'import des autres modules.
"""

from __future__ import annotations

import importlib
import sys

import jarvis_config
import jarvis_security


def test_user_name_depuis_env_a_cote_de_l_exe(monkeypatch, tmp_path):
    """En mode frozen, JARVIS_USER_NAME du .env voisin de l'exe est applique."""
    (tmp_path / ".env").write_text("JARVIS_USER_NAME=Tony\n", encoding="utf-8")
    cwd_temporaire = tmp_path / "meipass"
    cwd_temporaire.mkdir()

    with monkeypatch.context() as m:
        m.setattr(sys, "frozen", True, raising=False)
        m.setattr(sys, "executable", str(tmp_path / "Jarvis.exe"))
        # setenv prealable : force monkeypatch a tracer la cle, sinon la valeur
        # posee par load_dotenv pendant le reload survivrait a l'undo (la cle
        # absente avant le test n'est pas enregistree par delenv seul).
        m.setenv("JARVIS_USER_NAME", "x")
        m.delenv("JARVIS_USER_NAME")
        # cwd = dossier temporaire sans .env, comme sys._MEIPASS dans le .exe
        m.chdir(cwd_temporaire)
        importlib.reload(jarvis_config)
        assert jarvis_config.USER_NAME == "Tony"

    # Restaure le module pour les autres tests (env nettoye par monkeypatch)
    importlib.reload(jarvis_config)


def test_user_name_defaut_sans_env(monkeypatch, tmp_path):
    """Sans .env ni variable d'environnement, USER_NAME retombe sur Monsieur."""
    cwd_vide = tmp_path / "vide"
    cwd_vide.mkdir()

    with monkeypatch.context() as m:
        m.setattr(sys, "frozen", True, raising=False)
        m.setattr(sys, "executable", str(tmp_path / "Jarvis.exe"))
        m.setenv("JARVIS_USER_NAME", "x")  # trace la cle (purge garantie a l'undo)
        m.delenv("JARVIS_USER_NAME")
        m.chdir(cwd_vide)
        importlib.reload(jarvis_config)
        assert jarvis_config.USER_NAME == "Monsieur"

    importlib.reload(jarvis_config)


def test_restreindre_acces_fichier_existant(tmp_path):
    """La restriction ACL reussit sur un fichier existant (icacls ou chmod)."""
    fichier = tmp_path / "secret.txt"
    fichier.write_text("secret", encoding="utf-8")
    assert jarvis_security.restreindre_acces_fichier(fichier) is True
    if sys.platform != "win32":
        assert (fichier.stat().st_mode & 0o777) == 0o600


def test_restreindre_acces_fichier_absent(tmp_path):
    """Fichier inexistant : False, sans exception (best-effort)."""
    assert jarvis_security.restreindre_acces_fichier(tmp_path / "absent.txt") is False
