"""Memoire vectorielle (RAG) locale de Jarvis via embeddings Ollama.

Indexe la memoire cle/valeur de Jarvis sous forme de vecteurs et permet une
recherche semantique (similarite cosinus) au lieu d'un simple match exact.
100% local : les embeddings sont calcules par Ollama (modele nomic-embed-text
par defaut), aucune cle API requise, aucune dependance pip nouvelle.

Degradation gracieuse : si Ollama est injoignable ou que le modele d'embedding
n'est pas installe, disponible() renvoie False et toutes les fonctions de
recherche renvoient un resultat vide sans jamais lever d'exception. L'appelant
(main2.py) retombe alors sur le comportement actuel (match exact).

Stockage : base SQLite locale (jarvis_memoire_vec.db, gitignore), une ligne par
cle, l'embedding serialise en bytes float32. Un cache memoire des vecteurs
charges accelere les recherches successives.

API publique (cf. CONTRAT PR B) :
    disponible() -> bool
    indexer(cle, valeur, timestamp="") -> bool
    supprimer(cle) -> bool
    reindexer_tout(memoire) -> int
    rechercher(query, k=5, seuil=0.0) -> list[dict]
    nb_indexes() -> int

Aucune fonction ne propage d'exception : tout est attrape et journalise.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests


# ============================================================
# Configuration
# ============================================================

# Meme defaut que main2.py / model_advisor_service.py, surchargeable via .env
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
# Modele d'embedding : leger, multilingue, ~274 Mo (`ollama pull nomic-embed-text`)
_EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text")

_TIMEOUT_EMBED = 30.0   # secondes — POST /api/embeddings (1er appel charge le modele)
_TIMEOUT_SONDE = 5.0    # secondes — sonde de disponibilite (plus courte)

# Cache de la sonde disponible() : evite de spammer Ollama a chaque recherche
_SONDE_TTL = 30.0       # secondes de validite du resultat memoise


def _dossier_donnees() -> Path:
    """Dossier ou lire/ecrire la base vectorielle. A cote de l'exe en mode
    PyInstaller (sys._MEIPASS est temporaire et efface a la sortie), sinon
    racine du repo. Garantit la persistance entre deux lancements.

    Calque sur jarvis_profile._dossier_donnees pour rester coherent.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


DB_PATH: Path = _dossier_donnees() / "jarvis_memoire_vec.db"


# ============================================================
# Etat interne (cache process)
# ============================================================

# Cache de la sonde de disponibilite : (timestamp, resultat_bool)
_sonde_cache: tuple[float, bool] | None = None

# Cache memoire des vecteurs charges depuis la base, pour des recherches rapides.
# Structure : {cle: {"valeur": str, "vec": np.ndarray(float32, normalise)}}
# None = pas encore charge (lazy). Invalide a chaque ecriture en base.
_cache_vecteurs: dict[str, dict[str, Any]] | None = None


# ============================================================
# Base SQLite
# ============================================================

def _connexion() -> sqlite3.Connection:
    """Ouvre la base et garantit le schema. Connexion neuve par appel
    (sqlite3 n'est pas thread-safe en partage de connexion)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memoire_vec ("
        "  cle TEXT PRIMARY KEY,"
        "  valeur TEXT NOT NULL,"
        "  timestamp TEXT DEFAULT '',"
        "  dim INTEGER NOT NULL,"
        "  embedding BLOB NOT NULL"
        ")"
    )
    return conn


def _invalider_cache() -> None:
    """Force le rechargement du cache memoire au prochain acces."""
    global _cache_vecteurs
    _cache_vecteurs = None


# ============================================================
# Embeddings Ollama
# ============================================================

def _embed(texte: str, timeout: float = _TIMEOUT_EMBED) -> np.ndarray | None:
    """Calcule l'embedding d'un texte via Ollama. None si indisponible.

    POST {OLLAMA_URL}/api/embeddings -> {"embedding": [float, ...]}.
    Le vecteur renvoye est normalise (norme L2 = 1) pour que le produit
    scalaire vaille directement la similarite cosinus.
    """
    try:
        texte = (texte or "").strip()
        if not texte:
            return None
        r = requests.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": texte},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        brut = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(brut, list) or not brut:
            return None
        vec = np.asarray(brut, dtype=np.float32)
        if vec.ndim != 1 or not np.all(np.isfinite(vec)):
            return None
        norme = float(np.linalg.norm(vec))
        if norme <= 0.0:
            return None
        return vec / norme
    except Exception:
        # Ollama down, modele absent, JSON inattendu... -> indisponible
        return None


# ============================================================
# Disponibilite
# ============================================================

def disponible() -> bool:
    """Vrai si Ollama repond et que le modele d'embedding fonctionne.

    Sonde un embedding de test, memoise le resultat _SONDE_TTL secondes pour
    ne pas interroger Ollama a chaque recherche. Jamais d'exception.
    """
    global _sonde_cache
    try:
        maintenant = time.monotonic()
        if _sonde_cache is not None:
            age = maintenant - _sonde_cache[0]
            if 0.0 <= age < _SONDE_TTL:
                return _sonde_cache[1]
        ok = _embed("test", timeout=_TIMEOUT_SONDE) is not None
        _sonde_cache = (maintenant, ok)
        return ok
    except Exception:
        _sonde_cache = (time.monotonic(), False)
        return False


# ============================================================
# Indexation
# ============================================================

def indexer(cle: str, valeur: str, timestamp: str = "") -> bool:
    """Upsert l'embedding de "cle: valeur" en base. Vrai si reussi.

    Le texte embed combine cle et valeur pour que la recherche matche aussi
    bien le sujet (cle) que le contenu (valeur). Jamais d'exception.
    """
    try:
        cle = (cle or "").strip()
        valeur = "" if valeur is None else str(valeur)
        if not cle:
            return False
        texte = f"{cle}: {valeur}".strip()
        vec = _embed(texte)
        if vec is None:
            return False
        blob = vec.astype(np.float32).tobytes()
        conn = _connexion()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO memoire_vec (cle, valeur, timestamp, dim, embedding)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(cle) DO UPDATE SET"
                    "   valeur=excluded.valeur,"
                    "   timestamp=excluded.timestamp,"
                    "   dim=excluded.dim,"
                    "   embedding=excluded.embedding",
                    (cle, valeur, str(timestamp or ""), int(vec.shape[0]), blob),
                )
        finally:
            conn.close()
        _invalider_cache()
        return True
    except Exception as e:
        print(f"[RAG] Echec indexation '{cle}' : {e}")
        return False


def supprimer(cle: str) -> bool:
    """Retire une cle de l'index. Vrai si une ligne a ete supprimee.

    Jamais d'exception.
    """
    try:
        cle = (cle or "").strip()
        if not cle:
            return False
        conn = _connexion()
        try:
            with conn:
                cur = conn.execute("DELETE FROM memoire_vec WHERE cle = ?", (cle,))
                supprime = cur.rowcount > 0
        finally:
            conn.close()
        if supprime:
            _invalider_cache()
        return supprime
    except Exception as e:
        print(f"[RAG] Echec suppression '{cle}' : {e}")
        return False


def reindexer_tout(memoire: dict) -> int:
    """Reconstruit l'index depuis la memoire complete {cle: {valeur, timestamp}}.

    Vide la table puis reindexe chaque entree. Tolere aussi une memoire au
    format plat {cle: "valeur"}. Retourne le nombre d'entrees indexees avec
    succes. Jamais d'exception.

    Si Ollama est indisponible, aucune entree n'est reindexee mais l'index
    existant est tout de meme vide (etat coherent : index a reconstruire plus
    tard quand Ollama sera de retour).
    """
    if not isinstance(memoire, dict):
        return 0
    try:
        conn = _connexion()
        try:
            with conn:
                conn.execute("DELETE FROM memoire_vec")
        finally:
            conn.close()
        _invalider_cache()
    except Exception as e:
        print(f"[RAG] Echec purge avant reindexation : {e}")
        return 0

    indexes = 0
    for cle, entree in memoire.items():
        try:
            if isinstance(entree, dict):
                valeur = entree.get("valeur", "")
                timestamp = entree.get("timestamp", "")
            else:
                valeur = entree
                timestamp = ""
            if indexer(str(cle), "" if valeur is None else str(valeur), str(timestamp or "")):
                indexes += 1
        except Exception as e:
            print(f"[RAG] Entree '{cle}' ignoree a la reindexation : {e}")
    return indexes


# ============================================================
# Recherche
# ============================================================

def _charger_cache() -> dict[str, dict[str, Any]]:
    """Charge (et memoise) tous les vecteurs de la base en memoire.

    Les embeddings sont relus depuis les bytes float32 et renormalises par
    securite. Retourne {} en cas d'erreur. Jamais d'exception.
    """
    global _cache_vecteurs
    if _cache_vecteurs is not None:
        return _cache_vecteurs

    cache: dict[str, dict[str, Any]] = {}
    try:
        conn = _connexion()
        try:
            rows = conn.execute(
                "SELECT cle, valeur, dim, embedding FROM memoire_vec"
            ).fetchall()
        finally:
            conn.close()
        for cle, valeur, dim, blob in rows:
            try:
                vec = np.frombuffer(blob, dtype=np.float32)
                if int(dim) > 0 and vec.shape[0] != int(dim):
                    # Ligne corrompue (dim incoherente) -> ignoree
                    continue
                norme = float(np.linalg.norm(vec))
                if norme <= 0.0 or not np.all(np.isfinite(vec)):
                    continue
                cache[cle] = {"valeur": valeur, "vec": vec / norme}
            except Exception:
                continue
    except Exception as e:
        print(f"[RAG] Echec chargement cache vecteurs : {e}")
        cache = {}

    _cache_vecteurs = cache
    return cache


def rechercher(query: str, k: int = 5, seuil: float = 0.0) -> list[dict]:
    """Recherche semantique : renvoie les entrees les plus proches de query.

    Args:
        query: texte de recherche.
        k: nombre max de resultats (>=1).
        seuil: score cosinus minimal pour qu'un resultat soit retenu (0..1).

    Returns:
        list[dict]: [{"cle", "valeur", "score"}] tries par score decroissant.
        [] si Ollama indisponible, index vide ou query vide. Jamais d'exception.
    """
    try:
        query = (query or "").strip()
        if not query:
            return []
        try:
            k = int(k)
        except Exception:
            k = 5
        if k < 1:
            k = 1
        try:
            seuil = float(seuil)
        except Exception:
            seuil = 0.0

        cache = _charger_cache()
        if not cache:
            return []

        vec_query = _embed(query)
        if vec_query is None:
            return []

        resultats: list[dict] = []
        for cle, item in cache.items():
            vec = item["vec"]
            if vec.shape[0] != vec_query.shape[0]:
                # Dimension differente (changement de modele d'embedding) -> ignore
                continue
            score = float(np.dot(vec_query, vec))
            if score >= seuil:
                resultats.append({"cle": cle, "valeur": item["valeur"], "score": round(score, 4)})

        resultats.sort(key=lambda d: -d["score"])
        return resultats[:k]
    except Exception as e:
        print(f"[RAG] Echec recherche : {e}")
        return []


def nb_indexes() -> int:
    """Nombre d'entrees actuellement indexees. 0 en cas d'erreur."""
    try:
        conn = _connexion()
        try:
            (total,) = conn.execute("SELECT COUNT(*) FROM memoire_vec").fetchone()
        finally:
            conn.close()
        return int(total)
    except Exception as e:
        print(f"[RAG] Echec comptage : {e}")
        return 0


if __name__ == "__main__":
    # Test manuel rapide : python jarvis_actions/memory_rag.py
    print(f"[RAG] DB_PATH = {DB_PATH}")
    print(f"[RAG] Ollama disponible : {disponible()}")
    print(f"[RAG] Entrees indexees : {nb_indexes()}")
    if disponible():
        indexer("voiture", "une Tesla Model 3 rouge", "2026-06-11")
        indexer("animal", "un chat noir nomme Felix", "2026-06-11")
        for res in rechercher("quel vehicule j'ai", k=3):
            print(f"  - {res['cle']} ({res['score']}) : {res['valeur']}")
