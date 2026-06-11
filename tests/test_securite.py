"""Tests du module jarvis_security (token d'appairage WebSocket).

Couvre : generation/persistance, verification temps constant, masquage qui ne
revele jamais le token, et regeneration qui invalide l'ancien token.

La fixture `securite` (conftest) redirige TOKEN_PATH vers tmp_path et vide le
cache : aucune ecriture dans le depot, chaque test part d'un etat neutre.
"""

from __future__ import annotations


def test_generation_persiste_et_memoise(securite, tmp_path):
    """get_ws_token genere un token, le persiste sur disque et le memoise."""
    token = securite.get_ws_token()
    assert isinstance(token, str) and token
    # Persistance sur disque dans tmp_path (jamais dans le depot).
    assert securite.TOKEN_PATH.exists()
    assert securite.TOKEN_PATH.read_text(encoding="utf-8").strip() == token
    # Appel suivant : meme valeur (memoise).
    assert securite.get_ws_token() == token


def test_env_prioritaire_sur_fichier(securite, monkeypatch):
    """La variable d'environnement JARVIS_WS_TOKEN prime sur fichier/generation."""
    monkeypatch.setenv("JARVIS_WS_TOKEN", "  token-env-explicite  ")
    monkeypatch.setattr(securite, "_token_cache", None)
    assert securite.get_ws_token() == "token-env-explicite"
    # L'override env ne doit pas creer de fichier.
    assert not securite.TOKEN_PATH.exists()


def test_verifier_token_compare_digest(securite):
    """verifier_token accepte le bon token et rejette mauvais / vide / None."""
    token = securite.get_ws_token()
    assert securite.verifier_token(token) is True
    assert securite.verifier_token(token + "x") is False
    assert securite.verifier_token("") is False
    assert securite.verifier_token(None) is False


def test_token_masque_ne_revele_pas(securite):
    """Le token masque cache le coeur du secret et ne contient pas le token brut."""
    token = securite.get_ws_token()
    masque = securite.token_masque()
    # Format "abcd...wxyz" : prefixe/suffixe seulement, jamais le token complet.
    assert masque != token
    assert token not in masque
    assert "..." in masque
    assert masque.startswith(token[:4])
    assert masque.endswith(token[-4:])


def test_token_masque_court_tout_asterisques(securite, monkeypatch):
    """Un token tres court (<=8) est masque entierement en asterisques."""
    monkeypatch.setattr(securite, "_token_cache", "abc")
    masque = securite.token_masque()
    assert masque == "***"
    assert "abc" not in masque


def test_regeneration_invalide_ancien(securite):
    """regenerer_token cree un nouveau token et invalide l'ancien appairage."""
    ancien = securite.get_ws_token()
    nouveau = securite.regenerer_token()
    assert nouveau != ancien
    # L'ancien token n'est plus valide, le nouveau l'est.
    assert securite.verifier_token(ancien) is False
    assert securite.verifier_token(nouveau) is True
    # Persistance mise a jour sur disque.
    assert securite.TOKEN_PATH.read_text(encoding="utf-8").strip() == nouveau


def test_token_relu_depuis_fichier(securite, monkeypatch):
    """Un token deja present sur disque est relu (pas de regeneration)."""
    securite.TOKEN_PATH.write_text("token-persiste-sur-disque", encoding="utf-8")
    monkeypatch.setattr(securite, "_token_cache", None)
    assert securite.get_ws_token() == "token-persiste-sur-disque"
