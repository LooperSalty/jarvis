"""Tests pytest des fonctions pures du cerveau local.

Importe depuis ``jarvis_brain_local`` (et non ``main2``) afin de ne dependre
d'aucune librairie lourde (pygame, google.genai, faster-whisper...).
"""

import pytest

from jarvis_brain_local import (
    nettoyer_commande,
    nettoyer_pour_tts,
    resoudre_conversion_localement,
    resoudre_francais_localement,
    resoudre_math_localement,
    resoudre_traduction_localement,
)


# --- resoudre_math_localement ----------------------------------------------

class TestMath:
    def test_addition_simple(self):
        res = resoudre_math_localement("combien font 2 plus 2")
        assert res is not None
        assert "4" in res
        assert "Monsieur" in res

    def test_multiplication(self):
        res = resoudre_math_localement("calcule 6 fois 7")
        assert res is not None
        assert "42" in res

    def test_division(self):
        res = resoudre_math_localement("10 divisé par 2")
        assert res is not None
        assert "5" in res

    def test_racine_carree(self):
        res = resoudre_math_localement("racine carrée de 9")
        assert res is not None
        assert "3" in res

    def test_resultat_entier_pas_de_virgule_flottante(self):
        # 4 / 2 = 2.0 -> doit etre formate en entier 2
        res = resoudre_math_localement("4 sur 2")
        assert res is not None
        assert "2.0" not in res
        assert "2" in res

    def test_non_mathematique_retourne_none(self):
        assert resoudre_math_localement("quel temps fait-il") is None

    def test_injection_refusee(self):
        # Aucune lettre/appel de fonction non whiteliste ne doit s'evaluer.
        res = resoudre_math_localement("calcule __import__('os')")
        assert res is None


# --- resoudre_francais_localement ------------------------------------------

class TestFrancais:
    def test_definition_connue(self):
        res = resoudre_francais_localement("c'est quoi ia")
        assert res is not None
        assert "Intelligence Artificielle" in res

    def test_conjugaison_etre(self):
        res = resoudre_francais_localement("conjugue le verbe être")
        assert res is not None
        assert "Je suis" in res

    def test_conjugaison_avoir(self):
        res = resoudre_francais_localement("conjugaison du verbe avoir")
        assert res is not None
        assert "J'ai" in res

    def test_mot_inconnu_retourne_none(self):
        assert resoudre_francais_localement("c'est quoi xyzabc") is None

    def test_question_hors_sujet_retourne_none(self):
        assert resoudre_francais_localement("bonjour jarvis") is None


# --- resoudre_conversion_localement ----------------------------------------

class TestConversion:
    def test_km_vers_miles(self):
        res = resoudre_conversion_localement("convertis 10 km en miles")
        assert res is not None
        assert "miles" in res

    def test_miles_vers_km(self):
        res = resoudre_conversion_localement("convertis 10 miles en km")
        assert res is not None
        assert "kilomètres" in res

    def test_celsius_vers_fahrenheit(self):
        res = resoudre_conversion_localement("100 degrés celsius en fahrenheit")
        assert res is not None
        assert "212" in res

    def test_fahrenheit_vers_celsius(self):
        res = resoudre_conversion_localement("32 degrés fahrenheit en celsius")
        assert res is not None
        assert "0" in res

    def test_euros_vers_dollars(self):
        res = resoudre_conversion_localement("convertis 100 euros en dollars")
        assert res is not None
        assert "dollars" in res

    def test_sans_conversion_retourne_none(self):
        assert resoudre_conversion_localement("quelle heure est-il") is None


# --- resoudre_traduction_localement ----------------------------------------

class TestTraduction:
    def test_traduction_anglais(self):
        res = resoudre_traduction_localement("traduis bonjour en anglais")
        assert res is not None
        assert "hello" in res

    def test_traduction_espagnol(self):
        res = resoudre_traduction_localement("traduis merci en espagnol")
        assert res is not None
        assert "gracias" in res

    def test_traduction_allemand(self):
        res = resoudre_traduction_localement("comment dit-on maison en allemand")
        assert res is not None
        assert "haus" in res

    def test_mot_inconnu_retourne_none(self):
        assert resoudre_traduction_localement("traduis abracadabra en anglais") is None

    def test_sans_demande_traduction_retourne_none(self):
        assert resoudre_traduction_localement("bonjour") is None


# --- nettoyer_pour_tts ------------------------------------------------------

class TestNettoyerPourTts:
    def test_retire_bloc_de_code_fence(self):
        res = nettoyer_pour_tts("Voici:\n```python\nprint('x')\n```\nFini.")
        assert "print" not in res
        assert "Voici" in res
        assert "Fini" in res

    def test_remplace_url_par_un_lien(self):
        res = nettoyer_pour_tts("Va sur https://example.com pour voir.")
        assert "https://example.com" not in res
        assert "un lien" in res

    def test_lien_markdown_garde_le_texte(self):
        res = nettoyer_pour_tts("Clique [ici](https://x.com) maintenant.")
        assert "ici" in res
        assert "https://x.com" not in res
        assert "(" not in res

    def test_retire_image_markdown(self):
        res = nettoyer_pour_tts("Regarde ![alt](http://img.png) ceci.")
        assert "img.png" not in res
        assert "alt" not in res

    def test_retire_inline_code(self):
        res = nettoyer_pour_tts("Tape `ls -la` dans le terminal.")
        assert "ls -la" not in res

    def test_retire_gras_et_titres(self):
        res = nettoyer_pour_tts("**Important** : # titre")
        assert "*" not in res
        assert "#" not in res
        assert "Important" in res

    def test_normalise_espaces(self):
        res = nettoyer_pour_tts("trop    d'espaces\n\nici")
        assert "  " not in res
        assert res == "trop d'espaces ici"


# --- nettoyer_commande ------------------------------------------------------

class TestNettoyerCommande:
    def test_retire_wake_word_simple(self):
        assert nettoyer_commande("Jarvis ouvre chrome") == "ouvre chrome"

    def test_retire_wake_word_avec_virgule(self):
        assert nettoyer_commande("Jarvis, allume la lumière") == "allume la lumière"

    def test_met_en_minuscules_et_strip(self):
        assert nettoyer_commande("  JARVIS quelle heure  ") == "quelle heure"

    def test_sans_wake_word_inchange_hors_casse(self):
        assert nettoyer_commande("ouvre la porte") == "ouvre la porte"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
