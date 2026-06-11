"""Affichage visuel pour Jarvis : ouvrir des fenetres pour MONTRER des choses.

Deux capacites :
- montrer_contenu : genere une page HTML autonome (theme sombre style Jarvis)
  dans %TEMP%/jarvis_affichage/ puis l'ouvre dans le navigateur par defaut.
  Gere aussi l'affichage d'une image locale ou l'ouverture directe d'une URL.
- ouvrir_fichier : ouvre un fichier/dossier existant avec l'app par defaut.

Ouverture cross-platform (double implementation) : os.startfile sous Windows,
"open" sous macOS, "xdg-open" en fallback Linux. Pour le HTML, webbrowser.open
est tente en premier.

Ce module est branche comme tool "show_content" dans la boucle agent Gemini
de main2.py (montrer_contenu), et executer() est appele dans la chaine de
detection locale par mots-cles comme pc_actions/dev_actions.
"""

from __future__ import annotations

import html
import os
import platform
import re
import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path

from jarvis_config import USER_NAME

IS_MAC = platform.system() == "Darwin"

# Dossier de travail pour les pages generees (purge via nettoyer_anciens)
DOSSIER_AFFICHAGE = Path(tempfile.gettempdir()) / "jarvis_affichage"

_EXTENSIONS_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")

# Page autonome, theme sombre Jarvis. Placeholders remplaces par .replace()
# (pas de .format() pour ne pas avoir a doubler les accolades CSS).
_TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITRE__</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #04060c;
    color: #d7e8f5;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px 20px;
  }
  .carte {
    background: linear-gradient(160deg, #0a1220 0%, #060a14 100%);
    border: 1px solid rgba(75, 225, 255, 0.25);
    border-radius: 14px;
    box-shadow: 0 0 40px rgba(75, 225, 255, 0.08);
    max-width: 860px;
    width: 100%;
    padding: 36px 42px;
  }
  h1 {
    color: #4be1ff;
    font-size: 1.5rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    border-bottom: 1px solid rgba(75, 225, 255, 0.2);
    padding-bottom: 14px;
    margin-bottom: 22px;
  }
  .contenu { line-height: 1.7; font-size: 1.02rem; }
  .contenu p { margin: 8px 0; }
  .contenu strong { color: #4be1ff; }
  .contenu ul { margin: 10px 0 10px 24px; }
  .contenu li { margin: 4px 0; }
  .contenu img {
    max-width: 100%;
    max-height: 80vh;
    display: block;
    margin: 0 auto;
    border-radius: 8px;
  }
  .signature {
    margin-top: 26px;
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-align: right;
    color: rgba(215, 232, 245, 0.35);
  }
</style>
</head>
<body>
  <div class="carte">
    <h1>__TITRE__</h1>
    <div class="contenu">__CORPS__</div>
    <div class="signature">J.A.R.V.I.S</div>
  </div>
</body>
</html>
"""


def _slug(texte: str) -> str:
    """Nom de fichier ASCII safe derive du titre (meme esprit qu'obsidian_memory)."""
    propre = re.sub(r"[^a-z0-9]+", "_", texte.lower()).strip("_")
    return propre[:40] or "affichage"


def _markdown_leger(texte: str) -> str:
    """Convertit un markdown minimal (gras, listes '- ', sauts de ligne) en HTML.

    Le contenu utilisateur est echappe AVANT toute conversion (html.escape)
    pour eviter toute injection HTML dans la page generee.
    """
    sain = html.escape(texte)
    sain = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", sain)
    lignes_html: list[str] = []
    en_liste = False
    for ligne in sain.splitlines():
        item = ligne.strip()
        if item.startswith("- "):
            if not en_liste:
                lignes_html.append("<ul>")
                en_liste = True
            lignes_html.append(f"<li>{item[2:].strip()}</li>")
            continue
        if en_liste:
            lignes_html.append("</ul>")
            en_liste = False
        if item:
            lignes_html.append(f"<p>{item}</p>")
    if en_liste:
        lignes_html.append("</ul>")
    return "\n".join(lignes_html)


def _ecrire_html(nom_base: str, contenu_html: str) -> Path:
    """Ecrit la page de facon ATOMIQUE (.tmp puis os.replace), retourne le chemin."""
    DOSSIER_AFFICHAGE.mkdir(parents=True, exist_ok=True)
    # Purge opportuniste des vieilles pages (best-effort, jamais bloquant)
    nettoyer_anciens()
    final = DOSSIER_AFFICHAGE / f"{nom_base}_{int(time.time() * 1000)}.html"
    tmp = final.with_suffix(".tmp")
    tmp.write_text(contenu_html, encoding="utf-8")
    os.replace(tmp, final)
    return final


def _ouvrir_plateforme(chemin: str) -> bool:
    """Double implementation : os.startfile (Windows), open (macOS), xdg-open (Linux)."""
    try:
        if os.name == "nt":
            os.startfile(chemin)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", chemin], shell=False)
        else:
            subprocess.Popen(["xdg-open", chemin], shell=False)
        return True
    except Exception:
        return False


def _ouvrir_dans_navigateur(chemin: Path) -> bool:
    """Ouvre une page HTML locale : webbrowser d'abord, fallback plateforme sinon."""
    try:
        uri = chemin.resolve().as_uri()
    except Exception:
        uri = str(chemin)
    try:
        if webbrowser.open(uri):
            return True
    except Exception:
        pass
    return _ouvrir_plateforme(str(chemin))


def _generer_et_ouvrir(titre: str, corps_html: str) -> tuple[str, bool]:
    """Assemble la page a partir du template, l'ecrit puis l'ouvre."""
    page = _TEMPLATE_HTML.replace("__TITRE__", html.escape(titre)).replace(
        "__CORPS__", corps_html
    )
    try:
        chemin = _ecrire_html(_slug(titre), page)
    except Exception as e:
        return f"Echec de generation de la page : {e}", False
    if _ouvrir_dans_navigateur(chemin):
        return f"C'est affiche a l'ecran, {USER_NAME}.", True
    return "Page generee mais impossible d'ouvrir le navigateur.", False


def _montrer_url(url: str) -> tuple[str, bool]:
    """Ouvre une URL http/https dans le navigateur par defaut."""
    if not url.lower().startswith(("http://", "https://")):
        return "URL refusee : seuls http et https sont acceptes.", False
    try:
        if webbrowser.open(url) or _ouvrir_plateforme(url):
            return f"J'ouvre la page, {USER_NAME}.", True
        return "Impossible d'ouvrir l'URL dans le navigateur.", False
    except Exception as e:
        return f"Echec ouverture URL : {e}", False


def _montrer_image(titre: str, chemin_image: str) -> tuple[str, bool]:
    """Page HTML qui affiche une image locale en grand (URI file:///)."""
    try:
        p = Path(os.path.expanduser(chemin_image.strip().strip('"').strip("'")))
        if not p.is_file():
            return f"Image introuvable : {chemin_image}", False
        if p.suffix.lower() not in _EXTENSIONS_IMAGE:
            return f"Ce fichier n'est pas une image reconnue : {p.name}", False
        uri = p.resolve().as_uri()
    except Exception as e:
        return f"Chemin d'image invalide : {e}", False
    corps = (
        f'<img src="{html.escape(uri, quote=True)}" '
        f'alt="{html.escape(p.name, quote=True)}">'
    )
    return _generer_et_ouvrir(titre, corps)


def montrer_contenu(
    titre: str, contenu: str, type_contenu: str = "texte"
) -> tuple[str, bool]:
    """Affiche du contenu a l'utilisateur dans une fenetre (navigateur par defaut).

    Args:
        titre: titre de la page affichee.
        contenu: selon type_contenu — texte/markdown leger, HTML brut,
            chemin d'une image locale, ou URL http(s).
        type_contenu: "texte" (defaut), "html", "image" ou "url".

    Returns:
        (reponse vocale pour Jarvis, succes).
    """
    if not isinstance(titre, str) or not isinstance(contenu, str):
        return "Parametres invalides pour l'affichage.", False
    titre_clean = titre.strip() or "Jarvis"
    contenu_clean = contenu.strip()
    type_clean = (type_contenu or "texte").strip().lower()
    if not contenu_clean:
        return "Rien a afficher : le contenu est vide.", False

    try:
        if type_clean == "url":
            return _montrer_url(contenu_clean)
        if type_clean == "image":
            return _montrer_image(titre_clean, contenu_clean)
        if type_clean == "html":
            return _generer_et_ouvrir(titre_clean, contenu_clean)
        if type_clean == "texte":
            return _generer_et_ouvrir(titre_clean, _markdown_leger(contenu_clean))
        return (
            f"Type de contenu inconnu : '{type_contenu}' "
            "(attendu : texte, html, image ou url).",
            False,
        )
    except Exception as e:
        return f"Echec de l'affichage : {e}", False


def ouvrir_fichier(chemin: str) -> tuple[str, bool]:
    """Ouvre un fichier ou dossier EXISTANT avec l'application par defaut.

    Refuse les chemins inexistants et les arguments commencant par "-"
    (protection contre l'injection d'argument dans open/xdg-open).
    """
    if not chemin or not isinstance(chemin, str):
        return "Aucun chemin fourni.", False
    brut = chemin.strip().strip('"').strip("'")
    if not brut:
        return "Aucun chemin fourni.", False
    if brut.startswith("-"):
        return "Chemin refuse : il commence par un tiret.", False
    try:
        p = Path(os.path.expanduser(brut))
        if not p.exists():
            return f"Le chemin '{brut}' n'existe pas, {USER_NAME}.", False
        if _ouvrir_plateforme(str(p.resolve())):
            return f"{p.name or str(p)} ouvert, {USER_NAME}.", True
        return f"Impossible d'ouvrir {p.name}.", False
    except Exception as e:
        return f"Echec ouverture : {e}", False


def nettoyer_anciens(max_age_h: int = 24) -> None:
    """Purge les fichiers d'affichage plus vieux que max_age_h heures.

    Best-effort : ne leve jamais (appele en tache de fond / a la generation).
    """
    try:
        if not DOSSIER_AFFICHAGE.exists():
            return
        limite = time.time() - max(1, int(max_age_h)) * 3600
        for f in DOSSIER_AFFICHAGE.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < limite:
                    f.unlink()
            except Exception:
                continue
    except Exception:
        pass


# "montre(-moi) le fichier X", "ouvre le dossier Y", "affiche le fichier Z"
_OUVRIR_FICHIER_RE = re.compile(
    r"\b(?:montre(?:[\s-]*moi)?|ouvre|affiche)\s+"
    r"(?:le\s+|la\s+|ce\s+|cette\s+|mon\s+|ma\s+|un\s+|une\s+)?"
    r"(?:fichier|dossier)\s+(.+)",
    re.I,
)


def executer(cmd: str) -> tuple[str | None, bool]:
    """Detection locale par mots-cles. Retourne (None, False) si non reconnue.

    Seules les ouvertures de fichier/dossier sont detectees ici ; les demandes
    d'affichage de contenu passent par l'IA qui appelle montrer_contenu en tool.
    """
    if not cmd:
        return None, False
    # Match sur la commande originale (re.I) pour preserver la casse du chemin
    m = _OUVRIR_FICHIER_RE.search(cmd.strip())
    if m:
        return ouvrir_fichier(m.group(1).strip())
    return None, False
