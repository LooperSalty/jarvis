"""Tests du chat code local (jarvis_actions/code_chat.py).

`_choisir_modele` est pur. `modeles_installes`/`repondre` pilotent requests -> mockes.
"""

from __future__ import annotations

from jarvis_actions import code_chat as cc


# ============================================================
# _choisir_modele — pur
# ============================================================

def test_choisir_modele_prefere_le_code(monkeypatch):
    monkeypatch.setattr(cc, "_MODELE_FORCE", "")
    mods = ["llama3.2:3b", "deepseek-coder-v2:lite", "qwen2.5:7b"]
    assert cc._choisir_modele(mods) == "deepseek-coder-v2:lite"


def test_choisir_modele_repli_qwen(monkeypatch):
    monkeypatch.setattr(cc, "_MODELE_FORCE", "")
    assert cc._choisir_modele(["llama3.2:3b", "qwen2.5:7b"]) == "qwen2.5:7b"


def test_choisir_modele_vide():
    assert cc._choisir_modele([]) == ""


def test_choisir_modele_force(monkeypatch):
    monkeypatch.setattr(cc, "_MODELE_FORCE", "qwen2.5:7b")
    # force respecte SEULEMENT s'il est installe
    assert cc._choisir_modele(["deepseek-coder-v2:lite", "qwen2.5:7b"]) == "qwen2.5:7b"
    assert cc._choisir_modele(["deepseek-coder-v2:lite"]) == "deepseek-coder-v2:lite"


# ============================================================
# modeles_installes — /api/tags mocke
# ============================================================

class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_modeles_installes(monkeypatch):
    payload = {"models": [{"name": "qwen2.5:7b"}, {"name": "deepseek-coder-v2:lite"}]}
    monkeypatch.setattr(cc.requests, "get", lambda *a, **k: _Resp(200, payload))
    assert cc.modeles_installes() == ["qwen2.5:7b", "deepseek-coder-v2:lite"]


def test_modeles_installes_ollama_down(monkeypatch):
    def _boom(*a, **k):
        raise OSError("refused")
    monkeypatch.setattr(cc.requests, "get", _boom)
    assert cc.modeles_installes() == []


# ============================================================
# repondre
# ============================================================

def test_repondre_prompt_vide():
    txt, ok = cc.repondre("   ")
    assert ok is False


def test_repondre_aucun_modele(monkeypatch):
    monkeypatch.setattr(cc, "_MODELE_FORCE", "")
    monkeypatch.setattr(cc, "modeles_installes", lambda *a, **k: [])
    txt, ok = cc.repondre("comment trier une liste ?")
    assert ok is False
    assert "modele" in txt.lower()


def test_repondre_succes(monkeypatch):
    captures = {}

    def _post(url, json=None, timeout=None):
        captures["url"] = url
        captures["json"] = json
        return _Resp(200, {"message": {"content": "Utilise sorted(liste)."}})

    monkeypatch.setattr(cc.requests, "post", _post)
    txt, ok = cc.repondre("trier une liste python", modele="deepseek-coder-v2:lite")
    assert ok is True
    assert "sorted" in txt
    assert captures["json"]["model"] == "deepseek-coder-v2:lite"
    # system prompt code en tete + le message user a la fin
    assert captures["json"]["messages"][0]["role"] == "system"
    assert captures["json"]["messages"][-1]["content"] == "trier une liste python"


def test_repondre_historique_injecte(monkeypatch):
    captures = {}
    monkeypatch.setattr(cc.requests, "post",
                        lambda url, json=None, timeout=None: captures.update(json=json) or _Resp(200, {"message": {"content": "ok"}}))
    hist = [{"role": "user", "content": "salut"}, {"role": "assistant", "content": "bonjour"}]
    cc.repondre("et ensuite ?", historique=hist, modele="qwen2.5:7b")
    roles = [m["role"] for m in captures["json"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_repondre_erreur_http(monkeypatch):
    monkeypatch.setattr(cc.requests, "post", lambda *a, **k: _Resp(500, {}))
    txt, ok = cc.repondre("x", modele="qwen2.5:7b")
    assert ok is False
    assert "500" in txt
