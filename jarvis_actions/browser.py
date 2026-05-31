"""Controle d'un navigateur Chromium par Jarvis via Playwright.

Permet a Jarvis de :
- Naviguer sur un site : "va sur youtube", "ouvre amazon"
- Faire des recherches : "cherche [...] sur google/youtube/amazon"
- Lire le contenu : "lis-moi la page", "resume cette page"
- Cliquer : "clique sur [texte]"
- Remplir un champ : "tape [texte] dans [champ]"
- Faire un screenshot : "screenshot", "prends une photo de l'ecran"
- Fermer le navigateur : "ferme le navigateur"

Le navigateur reste ouvert entre les commandes (singleton lazy-init).
Mode visible (headless=False) pour que tu voies ce que Jarvis fait.

Pre-requis : pip install playwright + playwright install chromium
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

# Lazy import : si playwright manque, le module s'importe quand meme
# (les fonctions echouent au 1er appel reel, pas au load).
_PLAYWRIGHT = None
_BROWSER = None
_CONTEXT = None
_PAGE = None
_INIT_LOCK = asyncio.Lock()


# ============================================================
# Cycle de vie du navigateur
# ============================================================

async def _ensure_browser():
    """Lance Chromium si pas encore fait (mode visible). Singleton."""
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE
    if _PAGE is not None and not _PAGE.is_closed():
        return _PAGE

    async with _INIT_LOCK:
        if _PAGE is not None and not _PAGE.is_closed():
            return _PAGE

        from playwright.async_api import async_playwright
        _PLAYWRIGHT = await async_playwright().start()

        # Chrome installe + visible. Profil persistant pour rester connecte
        # aux comptes Google/YouTube/etc. d'une session a l'autre.
        profile_dir = Path(tempfile.gettempdir()) / "jarvis_browser_profile"
        profile_dir.mkdir(exist_ok=True)

        _CONTEXT = await _PLAYWRIGHT.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
            ],
            locale="fr-FR",
        )
        _BROWSER = _CONTEXT.browser
        _PAGE = _CONTEXT.pages[0] if _CONTEXT.pages else await _CONTEXT.new_page()
        print(f"[BROWSER] Chromium lance (profil: {profile_dir})")
    return _PAGE


async def _close_browser():
    """Ferme proprement le navigateur."""
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE
    try:
        if _CONTEXT:
            await _CONTEXT.close()
        if _PLAYWRIGHT:
            await _PLAYWRIGHT.stop()
    except Exception:
        pass
    _PLAYWRIGHT = _BROWSER = _CONTEXT = _PAGE = None
    print("[BROWSER] Ferme")


# ============================================================
# Operations primitives
# ============================================================

# Sites connus -> URL (matche pc_actions._WEB_SHORTCUTS mais en plus complet)
_SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "amazon": "https://www.amazon.fr",
    "wikipedia": "https://fr.wikipedia.org",
    "github": "https://github.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "stackoverflow": "https://stackoverflow.com",
    "leboncoin": "https://www.leboncoin.fr",
    "lemonde": "https://www.lemonde.fr",
    "lequipe": "https://www.lequipe.fr",
    "lefigaro": "https://www.lefigaro.fr",
    "twitch": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "discord": "https://discord.com/app",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
}


def _resolve_url(target: str) -> str:
    """Convertit 'youtube' / 'site.com' / 'https://...' en URL absolue."""
    target = target.strip().rstrip(".,!? ").lower()
    if target in _SITES:
        return _SITES[target]
    if target.startswith(("http://", "https://")):
        return target
    if "." in target and " " not in target:
        return f"https://{target}"
    # Sinon : recherche Google
    from urllib.parse import quote_plus
    return f"https://www.google.com/search?q={quote_plus(target)}"


async def navigate(url_or_site: str) -> tuple[bool, str]:
    page = await _ensure_browser()
    url = _resolve_url(url_or_site)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        title = await page.title()
        return True, f"Ouvert : {title or url_or_site}"
    except Exception as e:
        return False, f"Echec navigation : {e}"


async def search(engine: str, query: str) -> tuple[bool, str]:
    """engine = google | youtube | amazon."""
    from urllib.parse import quote_plus
    q = quote_plus(query)
    urls = {
        "google": f"https://www.google.com/search?q={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "amazon": f"https://www.amazon.fr/s?k={q}",
    }
    url = urls.get(engine, urls["google"])
    page = await _ensure_browser()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return True, f"Recherche '{query}' lancee sur {engine}"
    except Exception as e:
        return False, f"Echec recherche : {e}"


async def click_text(text: str) -> tuple[bool, str]:
    page = await _ensure_browser()
    try:
        # Essai 1 : role-based locator (plus fiable, prend texte accessible)
        loc = page.get_by_text(text, exact=False).first
        await loc.click(timeout=5000)
        return True, f"Clique sur '{text}'"
    except Exception:
        try:
            # Fallback : selecteur CSS large
            await page.click(f"text={text}", timeout=5000)
            return True, f"Clique sur '{text}'"
        except Exception as e:
            return False, f"Element '{text}' introuvable : {e}"


async def fill_field(field_hint: str, value: str) -> tuple[bool, str]:
    """Remplit un champ. field_hint = label visible, placeholder, ou nom."""
    page = await _ensure_browser()
    try:
        loc = page.get_by_label(field_hint).first
        await loc.fill(value, timeout=4000)
        return True, f"Rempli '{field_hint}' avec '{value}'"
    except Exception:
        try:
            loc = page.get_by_placeholder(field_hint).first
            await loc.fill(value, timeout=4000)
            return True, f"Rempli '{field_hint}' avec '{value}'"
        except Exception as e:
            return False, f"Champ '{field_hint}' introuvable : {e}"


async def read_main_text(max_chars: int = 1500) -> tuple[bool, str]:
    """Extrait le texte principal de la page (heuristique : <main>, <article>,
    sinon body). Tronque a max_chars."""
    page = await _ensure_browser()
    try:
        text = await page.evaluate("""
            () => {
                const candidates = ['main', 'article', '[role=main]'];
                for (const sel of candidates) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.length > 200) return el.innerText;
                }
                return document.body.innerText;
            }
        """)
        text = (text or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        title = await page.title()
        return True, f"[{title}]\n{text}"
    except Exception as e:
        return False, f"Echec lecture : {e}"


async def screenshot() -> tuple[bool, str]:
    page = await _ensure_browser()
    path = Path(tempfile.gettempdir()) / "jarvis_screenshot.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        return True, f"Screenshot enregistre : {path}"
    except Exception as e:
        return False, f"Echec screenshot : {e}"


async def play_liked_shuffle() -> tuple[bool, str]:
    """Ouvre la playlist YouTube 'Liked videos' (LL) et lance le shuffle.
    Necessite d'etre connecte a YouTube dans le profil Chromium persistant
    (la 1ere fois, fais 'va sur youtube' puis connecte-toi normalement)."""
    page = await _ensure_browser()
    try:
        # Page de la playlist Likes (LL = personal Liked videos)
        await page.goto("https://www.youtube.com/playlist?list=LL",
                        wait_until="domcontentloaded", timeout=15000)

        # Attend que la liste soit chargee + clique le bouton Shuffle.
        # YouTube a plusieurs boutons "Lecture aleatoire" sur la page (header
        # + sidebar) — on essaie plusieurs selecteurs.
        selectors = [
            'button[aria-label*="aléatoire" i]',     # FR
            'button[aria-label*="aleatoire" i]',
            'button[aria-label*="Shuffle" i]',       # EN
            'a[aria-label*="aléatoire" i]',
            'a[aria-label*="Shuffle" i]',
            'ytd-button-renderer:has-text("Lecture aléatoire")',
            'ytd-button-renderer:has-text("Shuffle")',
        ]
        clicked = False
        for sel in selectors:
            try:
                await page.locator(sel).first.click(timeout=2500)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            # Fallback : clique le 1er bouton Play sur la page
            try:
                await page.get_by_label("Tout lire").first.click(timeout=2500)
            except Exception:
                try:
                    await page.get_by_label("Play all").first.click(timeout=2500)
                except Exception:
                    return False, ("J'ai ouvert la playlist Likes mais je n'arrive pas "
                                   "a cliquer sur Lecture aleatoire. Verifie que tu es "
                                   "connecte a YouTube dans ce navigateur.")

        # Plein ecran : touche 'f' apres ~3s
        await asyncio.sleep(3)
        try:
            await page.keyboard.press("f")
        except Exception:
            pass
        return True, "Playlist Likes lancee en lecture aleatoire."
    except Exception as e:
        return False, f"Echec lancement playlist : {e}"


# ============================================================
# Detection mots-cles + dispatcher
# ============================================================

# Sites detectes apres "va sur / ouvre / navigue sur"
_SITES_PATTERN = "|".join(re.escape(s) for s in _SITES)

# "ouvre / va sur / navigue sur / aller a + (site|url)"
_RE_NAVIGATE = re.compile(
    r"\b(?:ouvre|va\s+sur|navigue\s+sur|aller\s+(?:sur|à)|rends\s+toi\s+sur)\s+"
    r"(?:(?:le\s+)?site\s+(?:de\s+|du\s+)?)?"
    r"([a-z0-9.\-/]+(?:\.[a-z]{2,})?[^\s]*|" + _SITES_PATTERN + r")",
    re.IGNORECASE,
)

# "cherche / recherche / trouve <X> sur <site>"  (Google par defaut)
_RE_SEARCH = re.compile(
    r"\b(?:cherche|recherche|trouve|google)\s+"
    r"(?:moi\s+)?"
    r"(.+?)"
    r"(?:\s+sur\s+(google|youtube|amazon))?$",
    re.IGNORECASE,
)

_RE_READ = re.compile(
    r"\b(?:lis(?:\s+moi)?|resume|r[ée]sume|que\s+dit)"
    r"(?:\s+(?:la\s+|le\s+|cette\s+))?"
    r"\s*(?:page|article|site|contenu)?",
    re.IGNORECASE,
)

_RE_CLICK = re.compile(
    r"\bclique[srz]?\s+(?:sur\s+)?(.+)",
    re.IGNORECASE,
)

_RE_TYPE = re.compile(
    r"\b(?:tape|saisis|[ée]cris)\s+(.+?)\s+dans\s+(.+)",
    re.IGNORECASE,
)

_RE_SCREENSHOT = re.compile(
    r"\b(?:screenshot|capture|prend(?:s|re)\s+(?:une\s+)?photo|captur[ée])",
    re.IGNORECASE,
)

_RE_CLOSE = re.compile(
    r"\bferme[srz]?\s+(?:le\s+)?navigateur|quitte\s+chrome",
    re.IGNORECASE,
)


async def async_executer(texte: str) -> tuple[str | None, bool]:
    """Routeur principal. Retourne (reponse_vocale, success) ou (None, False).

    Ordre des tests : commandes les plus specifiques en premier."""
    t = texte.strip()

    if _RE_CLOSE.search(t):
        await _close_browser()
        return "Navigateur ferme.", True

    if _RE_SCREENSHOT.search(t):
        ok, msg = await screenshot()
        return msg, ok

    if _RE_READ.search(t) and _PAGE is not None:
        # Demande de lecture seulement si un browser est deja ouvert
        ok, msg = await read_main_text()
        return msg, ok

    m = _RE_TYPE.search(t)
    if m:
        value, field = m.group(1).strip(), m.group(2).strip()
        ok, msg = await fill_field(field, value)
        return msg, ok

    m = _RE_NAVIGATE.search(t)
    if m:
        target = m.group(1).strip(".,!? ")
        ok, msg = await navigate(target)
        return msg, ok

    m = _RE_SEARCH.search(t)
    if m:
        query = m.group(1).strip(".,!? ")
        engine = (m.group(2) or "google").lower()
        ok, msg = await search(engine, query)
        return msg, ok

    m = _RE_CLICK.search(t)
    if m and _PAGE is not None:
        # Click only if a page is loaded (otherwise too risky to interpret)
        target = m.group(1).strip(".,!? ")
        ok, msg = await click_text(target)
        return msg, ok

    return None, False


async def shutdown():
    """A appeler au quit pour fermer proprement Chromium."""
    await _close_browser()
