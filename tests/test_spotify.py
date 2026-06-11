"""Tests du module Spotify (jarvis_actions.spotify) — logique pure.

Aucun appel reseau ni OAuth : on teste la disponibilite (identifiants absents)
et la detection d'intention par mots-cles. Quand Spotify n'est pas configure,
toute commande reconnue retombe sur (None, False) pour laisser la chaine de
fallback de main2 prendre le relais.

La fixture `spotify` (conftest) supprime les identifiants de l'environnement et
remet le client memoise a zero.
"""

from __future__ import annotations


def test_disponible_false_sans_cles(spotify):
    """Sans SPOTIFY_CLIENT_ID/SECRET, disponible() renvoie False."""
    assert spotify.disponible() is False


def test_executer_bonjour_non_reconnu(spotify):
    """Une phrase hors-scope renvoie (None, False)."""
    assert spotify.executer("bonjour") == (None, False)


def test_executer_vide(spotify):
    """Une commande vide renvoie (None, False)."""
    assert spotify.executer("") == (None, False)
    assert spotify.executer(None) == (None, False)


def test_executer_play_sans_spotify_mot_non_route(spotify):
    """'joue X' sans mentionner spotify n'est PAS capture (None, False).

    Le module ne vole pas un 'joue/mets X' generique : il exige 'spotify'.
    """
    assert spotify.executer("joue de la musique") == (None, False)


def test_executer_intention_reconnue_mais_non_configure(spotify):
    """Une intention Spotify claire mais module non configure -> (None, False).

    'joue X sur spotify' matche l'intention play, mais comme disponible() est
    False (pas de cles), on retombe sur (None, False) avant tout reseau.
    """
    assert spotify.executer("joue Daft Punk sur spotify") == (None, False)


def test_executer_pause_non_configure(spotify):
    """'pause' (controle media generique) sans config -> (None, False)."""
    assert spotify.executer("pause") == (None, False)


def test_nettoyer_titre_generique(spotify):
    """_nettoyer_titre renvoie None pour un titre vide ou generique."""
    assert spotify._nettoyer_titre(None) is None
    assert spotify._nettoyer_titre("  ") is None
    assert spotify._nettoyer_titre("la musique") is None
    assert spotify._nettoyer_titre("musique") is None


def test_nettoyer_titre_reel(spotify):
    """_nettoyer_titre conserve un vrai titre en retirant le 'sur spotify' final."""
    # Le suffixe ' sur spotify' est retire et le titre nettoye conserve.
    assert spotify._nettoyer_titre("Get Lucky sur spotify") == "Get Lucky"
    assert spotify._nettoyer_titre("  Around the World  ") == "Around the World"
    # Quotes entourant entierement le titre sont retirees.
    assert spotify._nettoyer_titre("'Get Lucky'") == "Get Lucky"


def test_regex_play_capture_titre(spotify):
    """La regex de play capture bien le titre apres 'joue'."""
    m = spotify._RE_PLAY.search("joue get lucky sur spotify")
    assert m is not None
    titre = spotify._nettoyer_titre(m.group("titre"))
    assert titre == "get lucky"


def test_regex_vol_up(spotify):
    """La regex de volume up matche 'monte le son spotify'."""
    assert spotify._RE_VOL_UP.search("monte le son sur spotify") is not None
    assert spotify._RE_VOL_DOWN.search("baisse le volume spotify") is not None
