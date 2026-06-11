"""Resume d'historique : compacte la conversation quand elle devient longue.

L'historique de Jarvis (`historique` dans main2) est une liste de
`types.Content` Gemini. Au fil d'une longue session il grossit, augmente la
latence et le cout des appels. Ce module resume les plus anciens echanges en un
court paragraphe FR et garde les N derniers messages intacts.

L'appel LLM est fourni par l'appelant via `demander` (async fn(prompt)->str),
pour eviter tout import circulaire et router vers Gemini ou Ollama.

Import de `google.genai.types` paresseux et tolerant : si la lib est absente,
`resumer_si_besoin` retourne None (degradation propre, on garde l'historique).
Aucune exception n'est jamais propagee.
"""

from __future__ import annotations

from typing import Awaitable, Callable

# Type de la callable LLM fournie par l'appelant.
Demander = Callable[[str], Awaitable[str]]

# Prompt FR demandant un resume concis des echanges les plus anciens.
_PROMPT_TEMPLATE = (
    "Voici le debut d'une conversation entre un utilisateur et son assistant "
    "vocal Jarvis. Resume ces echanges en un paragraphe FR concis (5 a 8 "
    "phrases maximum) qui conserve les informations importantes : ce que "
    "l'utilisateur a demande, les faits le concernant, les decisions prises et "
    "le contexte utile pour la suite. Ecris a la 3e personne, sans formule "
    "d'introduction, juste le resume.\n\n"
    "--- Echanges a resumer ---\n"
    "{transcript}\n"
    "--- Fin ---\n\n"
    "Resume :"
)


def _charger_types():
    """Import paresseux et tolerant de google.genai.types.

    Retourne le module `types` ou None si la lib est indisponible.
    """
    try:
        from google.genai import types  # import paresseux

        return types
    except Exception as e:  # noqa: BLE001 - lib absente ou cassee -> degradation
        print(f"[HISTORY_SUMMARY] google.genai indisponible : {e}")
        return None


def _texte_de_content(content) -> str:
    """Extrait le texte du premier part d'un Content Gemini de facon tolerante."""
    try:
        parts = getattr(content, "parts", None)
        if not parts:
            return ""
        texte = getattr(parts[0], "text", None)
        return texte.strip() if isinstance(texte, str) else ""
    except Exception:  # noqa: BLE001 - structure inattendue
        return ""


def _construire_transcript(messages: list) -> str:
    """Transforme une liste de Content en transcript lisible 'Role : texte'."""
    lignes: list[str] = []
    for content in messages:
        role = getattr(content, "role", "") or ""
        qui = "Jarvis" if role == "model" else "Utilisateur"
        texte = _texte_de_content(content)
        if texte:
            lignes.append(f"{qui} : {texte}")
    return "\n".join(lignes)


async def resumer_si_besoin(
    historique: list,
    demander: Demander,
    seuil: int = 60,
    garder: int = 30,
) -> list | None:
    """Resume les plus anciens echanges si l'historique depasse le seuil.

    Args:
        historique: liste de `types.Content` Gemini (role user/model).
        demander: callable async(prompt) -> str (appel LLM) fournie par l'appelant.
        seuil: nombre de messages au-dela duquel on compacte (defaut 60).
        garder: nombre de messages recents conserves intacts (defaut 30).

    Returns:
        Une NOUVELLE liste compactee = [resume] + les `garder` derniers messages,
        ou None s'il n'y a rien a faire (historique court, lib absente, erreur).
        L'historique d'origine n'est jamais mute.
    """
    # Garde-fous : rien a faire si trop court ou parametres incoherents.
    if not isinstance(historique, list) or len(historique) <= seuil:
        return None
    if garder < 0:
        garder = 0
    if garder >= len(historique):
        return None

    types = _charger_types()
    if types is None:
        return None

    # Les plus anciens a resumer = tout sauf les `garder` derniers.
    anciens = historique[: len(historique) - garder]
    recents = historique[len(historique) - garder :]

    transcript = _construire_transcript(anciens)
    if not transcript:
        # Rien d'exploitable a resumer -> on ne touche pas l'historique.
        return None

    prompt = _PROMPT_TEMPLATE.format(transcript=transcript)

    try:
        resume = await demander(prompt)
    except Exception as e:  # noqa: BLE001 - on ne doit jamais tuer l'appelant
        print(f"[HISTORY_SUMMARY] Echec appel LLM : {e}")
        return None

    if not isinstance(resume, str) or not resume.strip():
        return None

    resume = resume.strip()

    try:
        # On insere une paire user/model pour preserver l'alternance des roles
        # attendue par Gemini (premier tour = user), quel que soit le role du
        # premier message conserve dans `recents`.
        contenu_resume = types.Content(
            role="user",
            parts=[types.Part(text="[Contexte] Resume de nos echanges precedents :\n" + resume)],
        )
        accuse = types.Content(
            role="model",
            parts=[types.Part(text="Compris, je garde ce contexte en tete.")],
        )
    except Exception as e:  # noqa: BLE001 - construction Content impossible
        print(f"[HISTORY_SUMMARY] Construction Content impossible : {e}")
        return None

    return [contenu_resume, accuse] + list(recents)
