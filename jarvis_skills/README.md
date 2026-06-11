# Skills Jarvis

Dossier de **skills auto-découverts** : chaque fichier `.py` déposé ici est
chargé automatiquement au démarrage par `jarvis_actions/skills_loader.py`.
Pas besoin de toucher à `main2.py` pour ajouter une capacité à Jarvis.

## Comment ça marche

1. Au premier appel, le loader scanne `jarvis_skills/*.py` (les fichiers
   commençant par `_` sont ignorés, ainsi que ce README).
2. Chaque fichier est importé via `importlib`. Un skill invalide ou qui
   plante à l'import est **loggué et ignoré** — il ne fait jamais crasher Jarvis.
3. Quand une commande vocale arrive, `executer_skills(cmd)` essaie chaque
   skill actif dans l'**ordre alphabétique** des noms. Le premier qui
   reconnaît la commande (réponse non `None`) gagne.
4. En mode `.exe` (PyInstaller), le dossier `jarvis_skills/` est cherché
   **à côté de l'exe** : tu peux donc ajouter des skills sans rebuild.

## Contrat d'un skill

Un skill doit définir **deux choses** :

- `SKILL` : un dict avec `nom`, `description`, `version`.
- `executer(cmd)` (sync) **et/ou** `async_executer(cmd)` (async), qui
  retournent toujours un tuple `(reponse, succes)` :

| Cas | Retour |
|-----|--------|
| Commande non reconnue | `(None, False)` — le loader passe au skill suivant |
| Reconnue et réussie | `("phrase à vocaliser", True)` |
| Reconnue mais échec | `("message d'erreur à vocaliser", False)` |

## Template complet

Copie ce fichier sous `jarvis_skills/mon_skill.py` et adapte :

```python
"""Mon skill : decris ici ce qu'il fait.

Mots-cles : "ma commande", "mon autre commande".
"""

from __future__ import annotations

import unicodedata

SKILL = {
    "nom": "mon_skill",
    "description": "Une phrase qui decrit ce que fait le skill.",
    "version": "1.0.0",
}

# Mots-cles SANS accents : la commande est normalisee avant comparaison
_MOTS_CLES = (
    "ma commande",
    "mon autre commande",
)


def _normaliser(texte: str) -> str:
    """Minuscules + suppression des accents (le STT renvoie du texte accentue)."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def executer(cmd: str) -> tuple[str | None, bool]:
    """Detecte et execute la commande. (None, False) si non reconnue."""
    try:
        c = _normaliser(cmd or "")
        if not any(mot in c for mot in _MOTS_CLES):
            return None, False
        # ... ta logique ici ...
        return "Voila, c'est fait !", True
    except Exception as e:
        print(f"[SKILL mon_skill] Erreur : {e}")
        return "Desole, mon skill a rencontre un probleme.", False
```

Variante **async** (si tu as besoin d'`await`, par ex. aiohttp, Playwright) :

```python
async def async_executer(cmd: str) -> tuple[str | None, bool]:
    """Version async, appelee via async_executer_skills()."""
    c = _normaliser(cmd or "")
    if "ma commande" not in c:
        return None, False
    # resultat = await mon_appel_async()
    return "Resultat async pret.", True
```

## Règles et bonnes pratiques

- **Jamais de crash** : tout `executer` doit être enveloppé d'un `try/except`.
  Le loader rattrape aussi les exceptions, mais sois propre.
- **Mots-clés sans accents + normalisation** : la reconnaissance vocale
  renvoie du texte accentué (« pièce », « vidéo »), `main2.py` ne normalise
  rien. Utilise le helper `_normaliser` du template.
- **Mots-clés spécifiques** : un skill est testé AVANT l'appel à l'IA.
  Un mot-clé trop générique (ex. `"ouvre"`) volerait des commandes destinées
  à `pc_actions` ou à Gemini/Ollama.
- **Pas de secrets en dur** : lis les clés via `os.environ` (`.env`).
- **Pas d'effet de bord à l'import** : le fichier est importé au démarrage ;
  ne lance rien de lourd au niveau module (lazy-init dans `executer`).
- **Nom unique** : si deux skills déclarent le même `SKILL["nom"]`, seul le
  premier (ordre alphabétique des fichiers) est gardé, l'autre est loggué.
- Un fichier dont le nom commence par `_` (ex. `_brouillon.py`) est ignoré.

## Activer / désactiver un skill

L'état est persisté dans `jarvis_skills/skills_config.json` :

```json
{
  "disabled": ["nom_du_skill_desactive"]
}
```

Tu peux éditer ce fichier à la main, ou passer par l'API du loader :

```python
from jarvis_actions import skills_loader

skills_loader.charger_skills()                  # scan + import (idempotent)
skills_loader.lister_skills()                   # [{nom, description, fichier, active}]
skills_loader.activer_skill("pile_ou_face", False)   # desactive (persiste)
skills_loader.executer_skills("pile ou face")        # ("...pile !", True)
await skills_loader.async_executer_skills("...")     # pour les skills async
```

## Tester un skill sans lancer Jarvis

```bash
python -c "from jarvis_actions import skills_loader as s; print(s.executer_skills('pile ou face'))"
python -c "from jarvis_actions import skills_loader as s; print(s.executer_skills('citation du jour'))"
python -c "from jarvis_actions import skills_loader as s; print(s.lister_skills())"
```

## Exemples fournis

| Fichier | Mots-clés | Effet |
|---------|-----------|-------|
| `pile_ou_face.py` | « pile ou face », « lance une pièce » | Tirage aléatoire avec une réponse fun |
| `citation_du_jour.py` | « citation du jour », « donne-moi une citation » | Citation dev/scientifique stable sur la journée (hash de la date) |
