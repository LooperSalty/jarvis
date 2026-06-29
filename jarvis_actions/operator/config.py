"""Config persistante de l'Operator (societe, TVA, compteur devis, regles de tri,
autonomie). Gitignore (jarvis_operator.json), modele examples/jarvis_operator_example.json.
Lu/ecrit a cote de l'exe en frozen (pattern _dossier_donnees), sinon racine du repo.
Toute valeur est VALIDEE (liste blanche / typage) : aucune donnee non fiable renvoyee.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _dossier_donnees() -> Path:
    """A cote de l'exe en mode frozen (persistance), sinon racine du repo (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # jarvis_actions/operator/ -> racine du repo (dev)
    return Path(__file__).resolve().parent.parent.parent


OPERATOR_PATH: Path = _dossier_donnees() / "jarvis_operator.json"

# Niveaux d'autonomie pour le tri email (liste blanche).
AUTONOMIE: tuple[str, ...] = (
    "tri_auto_reponses_validees",  # classe/archive seul ; reponses en brouillon a valider
    "tout_en_validation",          # rien sans accord (propose tri ET reponses)
    "autonomie_totale",            # trie, archive ET repond/envoie seul
    "tri_auto_seul",               # trie/archive et rapporte ; jamais de reponse
)

DEFAUTS: dict[str, Any] = {
    "societe": {"nom": "", "adresse": "", "siret": "", "email": "", "tel": "", "iban": ""},
    "autonomie_email": "tri_auto_reponses_validees",
    "triage_intervalle_min": 15,
    "regles_tri": [],  # [{"si_contient": "facture", "label": "Factures", "archiver": false}]
    "devis": {
        "prefixe": "DEV",
        "compteur": 0,
        "tva_taux_defaut": 20.0,
        "validite_jours": 30,
        "mentions": "",
    },
    "plages_horaires": {"debut": "09:00", "fin": "18:00"},
}


def _num(v: Any, defaut: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def _int(v: Any, defaut: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return defaut


def _str(v: Any) -> str:
    return str(v or "").strip()


def _normaliser(brut: Any) -> dict[str, Any]:
    """Construit une config complete et VALIDE depuis un dict potentiellement
    partiel ou corrompu (chaque champ retombe sur son defaut si invalide)."""
    src = brut if isinstance(brut, dict) else {}
    soc = src.get("societe") if isinstance(src.get("societe"), dict) else {}
    dev = src.get("devis") if isinstance(src.get("devis"), dict) else {}
    pl = src.get("plages_horaires") if isinstance(src.get("plages_horaires"), dict) else {}
    aut = _str(src.get("autonomie_email")).lower()
    regles = src.get("regles_tri")
    regles = [r for r in regles if isinstance(r, dict)] if isinstance(regles, list) else []
    return {
        "societe": {k: _str(soc.get(k)) for k in DEFAUTS["societe"]},
        "autonomie_email": aut if aut in AUTONOMIE else DEFAUTS["autonomie_email"],
        "triage_intervalle_min": max(1, _int(src.get("triage_intervalle_min"), 15)),
        "regles_tri": regles,
        "devis": {
            "prefixe": _str(dev.get("prefixe")) or "DEV",
            "compteur": max(0, _int(dev.get("compteur"), 0)),
            "tva_taux_defaut": _num(dev.get("tva_taux_defaut"), 20.0),
            "validite_jours": max(1, _int(dev.get("validite_jours"), 30)),
            "mentions": _str(dev.get("mentions")),
        },
        "plages_horaires": {
            "debut": _str(pl.get("debut")) or "09:00",
            "fin": _str(pl.get("fin")) or "18:00",
        },
    }


def charger() -> dict[str, Any]:
    """Config Operator complete et validee (defauts si fichier absent/illisible)."""
    if not OPERATOR_PATH.exists():
        return _normaliser({})
    try:
        return _normaliser(json.loads(OPERATOR_PATH.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"[OPERATOR-CONFIG] Lecture echouee : {e}")
        return _normaliser({})


def sauvegarder(updates: Any) -> dict[str, Any]:
    """Fusionne un dict PARTIEL `updates` (1 niveau profond pour societe/devis/
    plages) avec la config existante, valide et ecrit atomiquement (.tmp +
    os.replace). Retourne la config complete. Ne leve jamais."""
    courant = charger()
    if isinstance(updates, dict):
        fusion = {**courant}
        for k, v in updates.items():
            if isinstance(v, dict) and isinstance(courant.get(k), dict):
                fusion[k] = {**courant[k], **v}
            else:
                fusion[k] = v
        courant = fusion
    config = _normaliser(courant)
    try:
        tmp = OPERATOR_PATH.with_name(OPERATOR_PATH.name + ".tmp")
        tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, OPERATOR_PATH)
    except Exception as e:
        print(f"[OPERATOR-CONFIG] Ecriture echouee : {e}")
    return config


def incrementer_compteur_devis() -> int:
    """Incremente et persiste le compteur de devis ; renvoie le nouveau numero."""
    config = charger()
    nouveau = config["devis"]["compteur"] + 1
    sauvegarder({"devis": {"compteur": nouveau}})
    return nouveau


if __name__ == "__main__":
    print(json.dumps(charger(), indent=2, ensure_ascii=False))
