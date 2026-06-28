"""Rendu PDF d'un devis (fpdf2, dependance OPTIONNELLE).

fpdf2 est importe paresseusement (lazy) : l'import de ce module reussit toujours,
meme sans fpdf installe. `disponible()` reflete la presence reelle de la lib et
`rendre()` se degrade proprement (retourne None) plutot que de lever.

Forme attendue d'un `devis` (tout champ est defensif, valeurs par defaut sinon) :
    {
        "numero": "DEV-2026-001",
        "date": "2026-06-28",                 # optionnel (defaut : aujourd'hui)
        "societe": {"nom", "adresse", "siret", "email", "tel", "iban"},
        "client": {"nom", "adresse", "email"},
        "lignes": [
            {"libelle", "quantite", "unite", "pu_ht", "tva_pct", "total_ht"},
            ...
        ],
        "totaux": {
            "total_ht": 0.0,
            "tva_par_taux": {"20.0": 0.0},     # detail TVA par taux
            "total_tva": 0.0,
            "total_ttc": 0.0,
        },
        "mentions": "Devis valable 30 jours.",
    }
"""

from __future__ import annotations

import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

# Sentinelle de memoisation du lazy import (distincte de None = "absent").
_UNSET: object = object()
_FPDF_CACHE: Any = _UNSET


def _charger_fpdf() -> Any:
    """Importe paresseusement la classe FPDF (fpdf2). Memoise. None si absent."""
    global _FPDF_CACHE
    if _FPDF_CACHE is _UNSET:
        try:
            from fpdf import FPDF  # type: ignore

            _FPDF_CACHE = FPDF
        except Exception:
            _FPDF_CACHE = None
    return _FPDF_CACHE


def disponible() -> bool:
    """True si fpdf2 est installe et donc le rendu PDF possible."""
    return _charger_fpdf() is not None


def _safe(valeur: Any) -> str:
    """Texte compatible polices coeur fpdf (latin-1) : remplace l'incompatible."""
    return str(valeur if valeur is not None else "").encode("latin-1", "replace").decode("latin-1")


def _nettoyer_nom(numero: Any) -> str:
    """Nom de fichier sur depuis un numero de devis (ASCII safe, jamais vide)."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", str(numero or "").strip()).strip("_")
    return base or "devis"


def _dossier_sortie(dossier: Any) -> Path:
    """Resout (et cree) le dossier de sortie : `dossier` ou temp/jarvis_devis."""
    base = Path(dossier) if dossier else Path(tempfile.gettempdir()) / "jarvis_devis"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cell(pdf: Any, w: float, h: float, txt: str, *, border: int = 0,
          align: str = "L", fill: bool = False, saut: bool = True) -> None:
    """Ecrit une cellule en absorbant les differences d'API fpdf2 (text/txt,
    new_x/new_y vs ln) selon la version installee."""
    t = _safe(txt)
    try:
        from fpdf.enums import XPos, YPos  # fpdf2 >= 2.7

        pdf.cell(
            w, h, text=t, border=border, align=align, fill=fill,
            new_x=XPos.LMARGIN if saut else XPos.RIGHT,
            new_y=YPos.NEXT if saut else YPos.TOP,
        )
    except Exception:
        pdf.cell(w, h, txt=t, border=border, align=align, fill=fill, ln=1 if saut else 0)


def _bloc(pdf: Any, lignes: list[str]) -> None:
    """Ecrit une suite de lignes de texte (ignore les vides)."""
    for ligne in lignes:
        if str(ligne).strip():
            _cell(pdf, 0, 6, str(ligne))


def _fmt_montant(valeur: Any) -> str:
    """Formate un montant en 'x.xx EUR' (0.00 si non numerique)."""
    try:
        return f"{float(valeur):.2f} EUR"
    except (TypeError, ValueError):
        return "0.00 EUR"


def _construire(pdf: Any, devis: dict[str, Any]) -> None:
    """Remplit le document : en-tete, client, tableau, totaux, mentions."""
    societe = devis.get("societe") if isinstance(devis.get("societe"), dict) else {}
    client = devis.get("client") if isinstance(devis.get("client"), dict) else {}
    lignes = devis.get("lignes") if isinstance(devis.get("lignes"), list) else []
    totaux = devis.get("totaux") if isinstance(devis.get("totaux"), dict) else {}
    numero = str(devis.get("numero") or "")
    quand = str(devis.get("date") or date.today().isoformat())

    pdf.add_page()

    # En-tete societe.
    pdf.set_font("Helvetica", "B", 16)
    _cell(pdf, 0, 10, str(societe.get("nom") or "Devis"))
    pdf.set_font("Helvetica", "", 10)
    _bloc(pdf, [
        societe.get("adresse", ""),
        f"SIRET : {societe.get('siret')}" if societe.get("siret") else "",
        societe.get("email", ""),
        societe.get("tel", ""),
    ])

    # Numero + date.
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    _cell(pdf, 0, 8, f"DEVIS {numero}")
    pdf.set_font("Helvetica", "", 10)
    _cell(pdf, 0, 6, f"Date : {quand}")

    # Bloc client.
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    _cell(pdf, 0, 7, "Client")
    pdf.set_font("Helvetica", "", 10)
    _bloc(pdf, [client.get("nom", ""), client.get("adresse", ""), client.get("email", "")])

    # Tableau des lignes.
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    entetes = [
        ("Libelle", 70), ("Qte", 18), ("Unite", 22),
        ("PU HT", 26), ("TVA %", 18), ("Total HT", 26),
    ]
    for titre, largeur in entetes[:-1]:
        _cell(pdf, largeur, 7, titre, border=1, fill=False, saut=False)
    _cell(pdf, entetes[-1][1], 7, entetes[-1][0], border=1)

    pdf.set_font("Helvetica", "", 9)
    for ligne in lignes:
        if not isinstance(ligne, dict):
            continue
        cols = [
            (str(ligne.get("libelle", "")), 70, "L"),
            (str(ligne.get("quantite", "")), 18, "R"),
            (str(ligne.get("unite", "")), 22, "L"),
            (_fmt_montant(ligne.get("pu_ht")), 26, "R"),
            (str(ligne.get("tva_pct", "")), 18, "R"),
            (_fmt_montant(ligne.get("total_ht")), 26, "R"),
        ]
        for i, (val, largeur, align) in enumerate(cols):
            _cell(pdf, largeur, 6, val, border=1, align=align, saut=(i == len(cols) - 1))

    # Totaux.
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    _cell(pdf, 0, 6, f"Total HT : {_fmt_montant(totaux.get('total_ht'))}")
    tva_par_taux = totaux.get("tva_par_taux") if isinstance(totaux.get("tva_par_taux"), dict) else {}
    for taux, montant in tva_par_taux.items():
        _cell(pdf, 0, 6, f"TVA {taux}% : {_fmt_montant(montant)}")
    _cell(pdf, 0, 6, f"Total TVA : {_fmt_montant(totaux.get('total_tva'))}")
    pdf.set_font("Helvetica", "B", 11)
    _cell(pdf, 0, 7, f"Total TTC : {_fmt_montant(totaux.get('total_ttc'))}")

    # Mentions legales.
    mentions = str(devis.get("mentions") or "").strip()
    if mentions:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 8)
        for ligne in mentions.splitlines():
            _cell(pdf, 0, 5, ligne)


def rendre(devis: Any, dossier: Any = None) -> str | None:
    """Genere le PDF du `devis` et renvoie son chemin (str). None si fpdf absent
    ou en cas d'echec (ne leve jamais).

    Le fichier est ecrit dans `dossier` (ou un sous-dossier temporaire
    jarvis_devis), nomme d'apres `devis["numero"]` nettoye, suffixe .pdf.
    """
    FPDF = _charger_fpdf()
    if FPDF is None:
        return None
    try:
        donnees = devis if isinstance(devis, dict) else {}
        chemin = _dossier_sortie(dossier) / f"{_nettoyer_nom(donnees.get('numero'))}.pdf"
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        _construire(pdf, donnees)
        Path(chemin).write_bytes(bytes(pdf.output()))
        return str(chemin)
    except Exception as e:  # degradation propre : on n'interrompt jamais l'Operator
        print(f"[OPERATOR-DEVIS-PDF] Rendu echoue : {e}")
        return None
