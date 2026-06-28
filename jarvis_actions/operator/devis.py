"""Modele de devis POLYVALENT (prestation / materiau / produit) + calculs PURS.

Toutes les fonctions sont sans effet de bord et defensives : une ligne ou un
total est toujours calculable, jamais d'exception non geree pour le parsing/calcul.
Ce module n'importe PAS config : la config du devis est passee en parametre.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Awaitable, Callable


def _num(v: Any, defaut: float = 0.0) -> float:
    """Convertit `v` en float, ou renvoie `defaut` si la valeur est invalide."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def ligne(
    libelle: str,
    type: str,
    quantite: Any,
    unite: str,
    pu_ht: Any,
    tva_pct: Any,
) -> dict:
    """Construit une ligne de devis normalisee.

    `type` est libre (valeurs attendues : prestation / materiau / produit).
    quantite, pu_ht et tva_pct sont coerces en float ; total_ht = quantite * pu_ht
    arrondi a 2 decimales. Ne leve jamais.
    """
    q = _num(quantite)
    pu = _num(pu_ht)
    tva = _num(tva_pct)
    return {
        "libelle": str(libelle or ""),
        "type": str(type or ""),
        "quantite": q,
        "unite": str(unite or ""),
        "pu_ht": pu,
        "tva_pct": tva,
        "total_ht": round(q * pu, 2),
    }


def calculer_totaux(lignes: Any) -> dict:
    """Calcule les totaux d'une liste de lignes (PUR, defensif).

    Renvoie {total_ht, tva_par_taux, total_tva, total_ttc}. tva_par_taux mappe
    chaque taux (float) -> montant de TVA arrondi pour les lignes a ce taux.
    """
    items = lignes if isinstance(lignes, list) else []
    total_ht = round(sum(_num(l.get("total_ht")) for l in items if isinstance(l, dict)), 2)

    base_par_taux: dict[float, float] = {}
    for l in items:
        if not isinstance(l, dict):
            continue
        taux = _num(l.get("tva_pct"))
        base_par_taux[taux] = base_par_taux.get(taux, 0.0) + _num(l.get("total_ht"))

    tva_par_taux = {
        taux: round(base * taux / 100, 2) for taux, base in base_par_taux.items()
    }
    total_tva = round(sum(tva_par_taux.values()), 2)
    total_ttc = round(total_ht + total_tva, 2)
    return {
        "total_ht": total_ht,
        "tva_par_taux": tva_par_taux,
        "total_tva": total_tva,
        "total_ttc": total_ttc,
    }


def numero_suivant(config_devis: Any) -> str:
    """Numero de devis au format `prefixe-annee-NNNN` (compteur+1 sur 4 chiffres).

    Defauts : prefixe="DEV", compteur=0. Ne leve jamais.
    """
    cfg = config_devis if isinstance(config_devis, dict) else {}
    prefixe = str(cfg.get("prefixe") or "DEV")
    try:
        compteur = int(cfg.get("compteur", 0))
    except (TypeError, ValueError):
        compteur = 0
    annee = datetime.now().year
    return f"{prefixe}-{annee}-{compteur + 1:04d}"


def construire(client: Any, lignes: Any, config: Any) -> dict:
    """Assemble un devis complet (numero, date, totaux, societe, mentions...).

    `config` attendu : {"devis": {...}, "societe": {...}}. Defensif : chaque
    champ retombe sur un defaut documente si absent/invalide. Ne leve jamais.
    """
    cfg = config if isinstance(config, dict) else {}
    dev = cfg.get("devis") if isinstance(cfg.get("devis"), dict) else {}
    items = lignes if isinstance(lignes, list) else []
    try:
        validite = int(dev.get("validite_jours", 30))
    except (TypeError, ValueError):
        validite = 30
    return {
        "numero": numero_suivant(dev),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "validite_jours": validite,
        "client": client if isinstance(client, dict) else {},
        "lignes": items,
        "totaux": calculer_totaux(items),
        "societe": cfg.get("societe", {}) if isinstance(cfg.get("societe"), dict) else {},
        "mentions": str(dev.get("mentions", "") or ""),
    }


def _extraire_json(texte: str) -> dict:
    """Extrait defensivement le premier bloc {...} d'un texte LLM ; {} si echec."""
    if not isinstance(texte, str):
        return {}
    debut = texte.find("{")
    fin = texte.rfind("}")
    if debut == -1 or fin == -1 or fin <= debut:
        return {}
    try:
        obj = json.loads(texte[debut : fin + 1])
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _prompt_extraction(transcript: str) -> str:
    """Construit le prompt d'extraction JSON a partir d'un transcript."""
    return (
        "Extrais de cette demande un devis au format JSON STRICT, sans texte autour.\n"
        'Schema attendu : {"client": {"nom": "", "email": ""}, '
        '"lignes": [{"libelle": "", "type": "prestation|materiau|produit", '
        '"quantite": 0, "unite": "", "pu_ht": 0, "tva_pct": 20}]}.\n'
        "type vaut prestation, materiau ou produit. Repond UNIQUEMENT le JSON.\n\n"
        f"Demande :\n{transcript}"
    )


async def from_transcript(
    transcript: str,
    demander_json: Callable[[str], Awaitable[str]],
    config: Any,
) -> dict:
    """Construit un devis a partir d'un transcript via un LLM (ASYNC, defensif).

    `demander_json` est une coroutine fn(prompt) -> str (reponse JSON brute).
    Parse le premier bloc accolades, mappe chaque ligne via ligne() (tva_pct par
    defaut = config["devis"].tva_taux_defaut, 20.0). En cas d'echec total ->
    devis vide via construire({}, [], config). Ne leve jamais.
    """
    cfg = config if isinstance(config, dict) else {}
    dev = cfg.get("devis") if isinstance(cfg.get("devis"), dict) else {}
    tva_defaut = _num(dev.get("tva_taux_defaut", 20.0), 20.0)

    try:
        brut = await demander_json(_prompt_extraction(str(transcript or "")))
    except Exception:
        return construire({}, [], cfg)

    data = _extraire_json(brut if isinstance(brut, str) else "")
    if not data:
        return construire({}, [], cfg)

    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    lignes_brutes = data.get("lignes") if isinstance(data.get("lignes"), list) else []
    lignes = [
        ligne(
            libelle=l.get("libelle", ""),
            type=l.get("type", ""),
            quantite=l.get("quantite", 0),
            unite=l.get("unite", ""),
            pu_ht=l.get("pu_ht", 0),
            tva_pct=l.get("tva_pct", tva_defaut) if l.get("tva_pct") is not None else tva_defaut,
        )
        for l in lignes_brutes
        if isinstance(l, dict)
    ]
    return construire(client, lignes, cfg)
