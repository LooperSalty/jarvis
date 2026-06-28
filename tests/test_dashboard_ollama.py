"""Tests de la decouverte/lancement Ollama du dashboard (jarvis_dashboard_api).

Regression du bug "le panneau de config dit qu'Ollama ne fonctionne pas alors
qu'il tourne" : sous Windows, "localhost" resout d'abord en IPv6 (::1) ou Ollama
n'ecoute pas, et le repli IPv6->IPv4 (~2 s) depasse le timeout court. Le check du
dashboard DOIT donc taper 127.0.0.1 (comme le reste de Jarvis), pas "localhost",
ET tolerer ~3 s pour ne pas faussement conclure "indisponible".

`_ollama_exe`, `_ollama_disponible`, `_lancer_ollama_pull`, `_modele_deja_installe`,
`_nom_modele_valide` sont purs/mockables (requests + subprocess + which -> mockes).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import jarvis_dashboard_api as jda


# ============================================================
# Helpers de mock
# ============================================================

def _popen_recorder():
    """Retourne (liste d'appels, classe FakePopen) capturant args ET kwargs."""
    calls: list[tuple[list[str], dict]] = []

    class FakePopen:
        def __init__(self, args, **kw):
            calls.append((list(args), kw))

    return calls, FakePopen


class _FakeRequests:
    """Mock minimal de `requests` : enregistre les appels GET."""

    def __init__(self, *, status=None, exc=None):
        self.status = status
        self.exc = exc
        self.calls: list[tuple[str, float]] = []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.exc is not None:
            raise self.exc

        class _Resp:
            status_code = self.status

        return _Resp()


# ============================================================
# URL / timeout Ollama — regression IPv4 vs localhost
# ============================================================

def test_ollama_tags_url_utilise_ipv4_pas_localhost():
    # Le bug : "localhost" -> timeout IPv6 sous Windows. 127.0.0.1 = direct.
    assert "localhost" not in jda.OLLAMA_TAGS_URL
    assert "127.0.0.1" in jda.OLLAMA_TAGS_URL
    assert jda.OLLAMA_TAGS_URL.endswith("/api/tags")


def test_ollama_timeout_couvre_le_repli_ipv6():
    # Doit couvrir le repli IPv6->IPv4 (~2 s) sinon la regression resurgit.
    assert jda.OLLAMA_TIMEOUT_S >= 3.0


def test_ollama_url_respecte_env_ollama_url(monkeypatch):
    # En Docker, OLLAMA_URL=http://ollama:11434 doit etre respecte (comme main2).
    import importlib

    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    try:
        importlib.reload(jda)
        assert jda.OLLAMA_TAGS_URL == "http://ollama:11434/api/tags"
    finally:
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        importlib.reload(jda)  # restaure le defaut pour les autres tests


# ============================================================
# _ollama_disponible — requests mocke (utilise bien l'URL IPv4)
# ============================================================

def test_ollama_disponible_vrai_si_200(monkeypatch):
    fake = _FakeRequests(status=200)
    monkeypatch.setattr(jda, "requests", fake)
    assert jda._ollama_disponible() is True
    # Tape bien l'URL IPv4 avec le timeout tolerant.
    assert fake.calls == [(jda.OLLAMA_TAGS_URL, jda.OLLAMA_TIMEOUT_S)]


def test_ollama_disponible_faux_si_erreur_reseau(monkeypatch):
    monkeypatch.setattr(jda, "requests", _FakeRequests(exc=OSError("timeout")))
    assert jda._ollama_disponible() is False


def test_ollama_disponible_faux_sans_requests(monkeypatch):
    monkeypatch.setattr(jda, "requests", None)
    assert jda._ollama_disponible() is False


# ============================================================
# _ollama_exe — PATH puis chemins d'install connus (ordre)
# ============================================================

def test_ollama_exe_prefere_le_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ollama")
    assert jda._ollama_exe() == "/usr/bin/ollama"


def test_ollama_exe_replie_sur_localappdata(monkeypatch, tmp_path):
    # which echoue (PATH fige sans Ollama) mais le binaire est a l'emplacement
    # d'install standard Windows -> on doit le retrouver quand meme.
    monkeypatch.setattr("shutil.which", lambda _name: None)
    install = tmp_path / "Programs" / "Ollama"
    install.mkdir(parents=True)
    exe = install / "ollama.exe"
    exe.write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert jda._ollama_exe() == str(exe)


def test_ollama_exe_localappdata_prioritaire_sur_programfiles(monkeypatch, tmp_path):
    # Les DEUX emplacements existent : LOCALAPPDATA (install par utilisateur,
    # cas reel de l'installeur Jarvis) doit gagner. Garde-fou contre une
    # inversion accidentelle de l'ordre des candidats.
    monkeypatch.setattr("shutil.which", lambda _name: None)
    local = tmp_path / "local"
    pf = tmp_path / "pf"
    (local / "Programs" / "Ollama").mkdir(parents=True)
    (local / "Programs" / "Ollama" / "ollama.exe").write_text("")
    (pf / "Ollama").mkdir(parents=True)
    (pf / "Ollama" / "ollama.exe").write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("ProgramFiles", str(pf))
    assert jda._ollama_exe() == str(local / "Programs" / "Ollama" / "ollama.exe")


def test_ollama_exe_replie_sur_programfiles(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    pf = tmp_path / "pf"
    (pf / "Ollama").mkdir(parents=True)
    exe = pf / "Ollama" / "ollama.exe"
    exe.write_text("")
    monkeypatch.setenv("ProgramFiles", str(pf))
    assert jda._ollama_exe() == str(exe)


def test_ollama_exe_introuvable(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    # Aucun fichier candidat n'existe -> None (independant de la machine).
    monkeypatch.setattr(Path, "is_file", lambda _self: False)
    assert jda._ollama_exe() is None


# ============================================================
# _lancer_ollama_pull — subprocess mocke
# ============================================================

def test_lancer_pull_ollama_introuvable(monkeypatch):
    monkeypatch.setattr(jda, "_ollama_exe", lambda: None)
    ok, msg = jda._lancer_ollama_pull("llama3.2:3b")
    assert ok is False
    assert "pas installe" in msg


def test_lancer_pull_lance_la_commande(monkeypatch):
    calls, FakePopen = _popen_recorder()
    monkeypatch.setattr(jda, "_ollama_exe", lambda: "/fake/ollama")
    monkeypatch.setattr(jda, "_ollama_disponible", lambda: True)  # serveur up
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    ok, msg = jda._lancer_ollama_pull("qwen2.5:7b")
    assert ok is True
    assert "qwen2.5:7b" in msg
    # Serveur deja up -> un seul appel : le pull avec "--" anti-injection.
    assert [args for args, _kw in calls] == [["/fake/ollama", "pull", "--", "qwen2.5:7b"]]
    # Sortie silencieuse (pas de fenetre/flux qui fuit).
    _args, kw = calls[0]
    assert kw["stdout"] is subprocess.DEVNULL
    assert kw["stderr"] is subprocess.DEVNULL
    assert "creationflags" in kw


def test_lancer_pull_demarre_serveur_puis_attend(monkeypatch):
    calls, FakePopen = _popen_recorder()
    etat = {"n": 0}

    def fake_dispo():
        # 1er appel (le "if not _ollama_disponible") -> False : declenche serve.
        # appels suivants (poll) -> True : la boucle d'attente sort aussitot.
        etat["n"] += 1
        return etat["n"] > 1

    monkeypatch.setattr(jda, "_ollama_exe", lambda: "/fake/ollama")
    monkeypatch.setattr(jda, "_ollama_disponible", fake_dispo)
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(jda.time, "sleep", lambda _s: None)  # pas d'attente reelle

    ok, _msg = jda._lancer_ollama_pull("llama3.2:3b")
    assert ok is True
    # Serveur eteint -> on le demarre AVANT de tirer le modele.
    assert [args for args, _kw in calls] == [
        ["/fake/ollama", "serve"],
        ["/fake/ollama", "pull", "--", "llama3.2:3b"],
    ]


# ============================================================
# Helpers purs deja existants
# ============================================================

def test_nom_modele_valide_rejette_injection_de_flag():
    assert jda._nom_modele_valide("llama3.2:3b") is True
    assert jda._nom_modele_valide("qwen2.5-coder:7b") is True
    assert jda._nom_modele_valide("--config") is False
    assert jda._nom_modele_valide("") is False
    assert jda._nom_modele_valide("a b") is False


def test_modele_deja_installe_compare_la_base():
    installes = ["qwen2.5:7b", "llama3.2:3b"]
    assert jda._modele_deja_installe("qwen2.5:7b", installes) is True
    assert jda._modele_deja_installe("qwen2.5", installes) is True  # base sans tag
    assert jda._modele_deja_installe("mistral:7b", installes) is False
