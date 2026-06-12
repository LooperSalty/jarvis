"""Tests du pattern _dossier_donnees (persistance des donnees en mode .exe).

En mode PyInstaller (sys.frozen), les donnees doivent etre lues/ecrites a cote
de l'executable — jamais dans sys._MEIPASS (temporaire, efface a la sortie).
En mode dev, elles restent a la racine du repo (dossier du module).

main2._dossier_donnees n'est pas teste ici : importer main2 declenche tout le
demarrage (clients IA, audio). Le pattern est identique a celui des modules
testes ci-dessous.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import jarvis_dashboard_api
import jarvis_profile


@pytest.mark.parametrize("module", [jarvis_dashboard_api, jarvis_profile])
def test_dossier_donnees_mode_dev(module):
    """Sans sys.frozen, le dossier de donnees est celui du module (racine repo)."""
    attendu = Path(module.__file__).resolve().parent
    assert module._dossier_donnees() == attendu


@pytest.mark.parametrize("module", [jarvis_dashboard_api, jarvis_profile])
def test_dossier_donnees_mode_frozen(module, monkeypatch, tmp_path):
    """Avec sys.frozen, le dossier de donnees est celui de l'exe (persistant)."""
    faux_exe = tmp_path / "Jarvis.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(faux_exe))
    assert module._dossier_donnees() == tmp_path
