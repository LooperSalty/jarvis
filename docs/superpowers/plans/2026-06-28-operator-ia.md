# Operator IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doter Jarvis d'un sous-système « Operator » qui trie la boîte mail (et rapporte), gère RDV/agenda, écoute des réunions (live + import audio), génère des devis PDF envoyés après validation « oui/non », et fait des recherches internet.

**Architecture:** Package `jarvis_actions/operator/` (petits modules), branché aux 3 surfaces existantes (voix `async_executer`, agent Gemini `tools()/dispatch()`, dashboard `dash_operator_*`) + un planificateur de fond. Cœur logique PUR et testé ; tous les effets de bord (Google, LLM, PDF, audio) isolés et injectés via `init(ctx)`.

**Tech Stack:** Python 3 (flat imports `jarvis_core/` + package `jarvis_actions`), google-api-python-client (Gmail/Calendar/Docs), Gemini/Ollama via `demander_ia`, faster-whisper (STT), fpdf2 (PDF, optionnel), SerpAPI + Playwright (recherche), frontend Vite/TS (dashboard), pytest.

## Global Constraints

- **Imports à plat** : `jarvis_core/` est sur `sys.path` (PAS de package), `jarvis_actions` est un package. Le sous-package `operator/` utilise des imports **relatifs** internes (`from . import config`), comme `pc_control/`.
- **Persistance frozen-safe** : tout fichier runtime résolu via `_dossier_donnees()` (= `Path(sys.executable).parent` si `sys.frozen`, sinon `Path(__file__).resolve().parent.parent` pour remonter de `jarvis_core/`… mais ce module est dans `jarvis_actions/operator/`, donc remonter de `.parent.parent.parent`). Voir Task 1.
- **Contrat action** : `executer/async_executer(cmd) -> tuple[str|None, bool]` ; `(None, False)` = non géré, la chaîne continue. Ne JAMAIS lever d'exception hors du module.
- **Immutabilité** : construire de nouveaux dicts, ne jamais muter les entrées (cf. `coding-style`).
- **Dégradation propre** : chaque dép externe optionnelle (`fpdf2`, `faster-whisper`, creds Google, `SERPAPI_API_KEY`) → message clair, jamais de crash.
- **Aucun envoi sortant** (email/devis) sans « oui » explicite via la file d'approbation.
- **Config validée par liste blanche** (pattern `jarvis_ui_config.py`), écriture atomique `.tmp` + `os.replace`.
- **Tests** : pytest, fichiers dans `tests/`, import `from jarvis_actions.operator import X`, isolation via `monkeypatch.setattr(mod, "OPERATOR_PATH", tmp_path / ...)`. AUCUN accès réseau (Google/LLM/SerpAPI mockés). Viser ≥ 80 % sur les modules purs.
- **Commits** : pas d'attribution Co-Authored-By (désactivée globalement). Format conventionnel `type(scope): desc`.
- **Encoding** : fichiers UTF-8 ; commentaires/strings sans accents problématiques côté console Windows si possible.

---

## File Structure

```
jarvis_actions/operator/
├── __init__.py        # façade : init(ctx), async_executer, _router (pur), tools(), dispatch(), demarrer_planificateur()
├── config.py          # jarvis_operator.json : société, TVA, compteur devis, règles tri, autonomie, plages — validé liste blanche
├── report.py          # journal d'activité (persisté) + resume() + broadcast operator_activity
├── approvals.py       # file d'approbation persistée (send_devis/send_email_reply) + confirmer/rejeter + broadcast operator_pending
├── prompts.py         # gabarits LLM (classif email, parse RDV, extraction devis, résumé réunion) — strings purs
├── gmail_ops.py       # threads, classif, étiquette/archive, brouillons — helpers purs + appels Gmail isolés
├── calendar_ops.py    # CRUD événements, créneaux libres, parse RDV — helpers purs + appels Calendar isolés
├── meeting.py         # transcription fichier + mode live (boucle continue) + résumé
├── devis.py           # modèle polyvalent + calculer_totaux (PUR) + numero_suivant + from_transcript
├── devis_pdf.py       # rendu PDF (fpdf2 optionnel) ; repli Google Doc
└── research.py        # SerpAPI/browser + synthèse LLM — shaping pur testé

examples/jarvis_operator_example.json     # modèle versionné
frontend/src/dashboard/sections_operator.ts  # onglet Operator
tests/test_operator_config.py
tests/test_operator_report.py
tests/test_operator_approvals.py
tests/test_operator_router.py
tests/test_operator_gmail.py
tests/test_operator_calendar.py
tests/test_operator_devis.py
tests/test_operator_meeting.py
tests/test_operator_research.py
```

Modifs : `jarvis_core/main2.py` (import + init + dispatch + scheduler + SCOPES), `jarvis_core/jarvis_dashboard_api.py` (handlers `dash_operator_*`), `frontend/src/dashboard/sections.ts` (register), `.gitignore`, `requirements-windows.txt`, `Jarvis.spec`/`JarvisWeb.spec` (hiddenimport fpdf si besoin), `CLAUDE.md`, `README.md`.

---

# PHASE 1 — Fondation (package + config + report + approvals + façade + wiring + coquille dashboard)

### Task 1: `operator/config.py` — config persistée et validée

**Files:**
- Create: `jarvis_actions/operator/__init__.py` (vide au départ, juste docstring de package)
- Create: `jarvis_actions/operator/config.py`
- Create: `examples/jarvis_operator_example.json`
- Modify: `.gitignore` (ajouter `jarvis_operator.json`)
- Test: `tests/test_operator_config.py`

**Interfaces:**
- Produces: `config.charger() -> dict`, `config.sauvegarder(updates: dict) -> dict`, `config.OPERATOR_PATH: Path`, constantes `DEFAUTS`, `TVA_TAUX`, `AUTONOMIE`.

- [ ] **Step 1: Écrire les tests (échouent)**

```python
# tests/test_operator_config.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def cfg(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.config")
    monkeypatch.setattr(mod, "OPERATOR_PATH", tmp_path / "jarvis_operator.json")
    return mod

def test_defauts_quand_absent(cfg):
    c = cfg.charger()
    assert c["societe"]["nom"] == ""
    assert c["autonomie_email"] == "tri_auto_reponses_validees"
    assert c["devis"]["compteur"] == 0
    assert c["devis"]["prefixe"] == "DEV"

def test_sauvegarde_partielle_et_validation(cfg):
    out = cfg.sauvegarder({"societe": {"nom": "ACME", "siret": "123"}})
    assert out["societe"]["nom"] == "ACME"
    # rechargement persistant
    assert cfg.charger()["societe"]["nom"] == "ACME"

def test_autonomie_invalide_retombe_defaut(cfg):
    out = cfg.sauvegarder({"autonomie_email": "n_importe_quoi"})
    assert out["autonomie_email"] == "tri_auto_reponses_validees"

def test_tva_taux_filtre_valeurs_non_numeriques(cfg):
    out = cfg.sauvegarder({"devis": {"tva_taux_defaut": "abc"}})
    assert out["devis"]["tva_taux_defaut"] == 20.0  # defaut

def test_increment_compteur_devis(cfg):
    assert cfg.incrementer_compteur_devis() == 1
    assert cfg.incrementer_compteur_devis() == 2
    assert cfg.charger()["devis"]["compteur"] == 2
```

- [ ] **Step 2: Lancer → échec**

Run: `python -m pytest tests/test_operator_config.py -q`
Expected: FAIL (`ModuleNotFoundError: jarvis_actions.operator.config`)

- [ ] **Step 3: Implémenter `config.py`** (calqué sur `jarvis_ui_config.py`)

```python
# jarvis_actions/operator/config.py
"""Config persistante de l'Operator (societe, TVA, compteur devis, regles de tri,
autonomie). Gitignore (jarvis_operator.json), modele examples/jarvis_operator_example.json.
Lu/ecrit a cote de l'exe en frozen (pattern _dossier_donnees), sinon racine du repo.
Toute valeur est VALIDEE (liste blanche / typage) : aucune donnee non fiable renvoyee."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from typing import Any

def _dossier_donnees() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # jarvis_actions/operator/ -> racine du repo (dev)
    return Path(__file__).resolve().parent.parent.parent

OPERATOR_PATH: Path = _dossier_donnees() / "jarvis_operator.json"

AUTONOMIE: tuple[str, ...] = (
    "tri_auto_reponses_validees", "tout_en_validation", "autonomie_totale", "tri_auto_seul",
)
DEFAUTS: dict[str, Any] = {
    "societe": {"nom": "", "adresse": "", "siret": "", "email": "", "tel": "", "iban": ""},
    "autonomie_email": "tri_auto_reponses_validees",
    "triage_intervalle_min": 15,
    "regles_tri": [],  # [{"si_contient": "facture", "label": "Factures", "archiver": false}]
    "devis": {
        "prefixe": "DEV", "compteur": 0, "tva_taux_defaut": 20.0,
        "validite_jours": 30, "mentions": "",
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
    if not OPERATOR_PATH.exists():
        return _normaliser({})
    try:
        return _normaliser(json.loads(OPERATOR_PATH.read_text(encoding="utf-8")))
    except Exception as e:
        print(f"[OPERATOR-CONFIG] Lecture echouee : {e}")
        return _normaliser({})

def sauvegarder(updates: Any) -> dict[str, Any]:
    courant = charger()
    if isinstance(updates, dict):
        # fusion immuable (1 niveau profond pour societe/devis/plages)
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
```

Et `jarvis_actions/operator/__init__.py` (docstring de package seulement pour l'instant) :

```python
"""Sous-systeme Operator de Jarvis : tri mail, RDV/agenda, reunion, devis, recherche.
Facade publique completee progressivement (cf. Task 4)."""
```

Et `examples/jarvis_operator_example.json` (copie de `DEFAUTS` avec valeurs d'exemple génériques, AUCUNE donnée réelle) :

```json
{
  "societe": {"nom": "Ma Societe", "adresse": "1 rue Exemple, 75000 Paris", "siret": "000 000 000 00000", "email": "contact@exemple.fr", "tel": "01 23 45 67 89", "iban": ""},
  "autonomie_email": "tri_auto_reponses_validees",
  "triage_intervalle_min": 15,
  "regles_tri": [{"si_contient": "facture", "label": "Factures", "archiver": false}],
  "devis": {"prefixe": "DEV", "compteur": 0, "tva_taux_defaut": 20.0, "validite_jours": 30, "mentions": "TVA non applicable, art. 293 B du CGI"},
  "plages_horaires": {"debut": "09:00", "fin": "18:00"}
}
```

- [ ] **Step 4: `.gitignore`** — ajouter après la ligne `jarvis_ui_config.json` :

```
# Config Operator perso (societe, compteur devis). Modele : examples/jarvis_operator_example.json
jarvis_operator.json
```

- [ ] **Step 5: Lancer → succès**

Run: `python -m pytest tests/test_operator_config.py -q`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add jarvis_actions/operator/__init__.py jarvis_actions/operator/config.py examples/jarvis_operator_example.json .gitignore tests/test_operator_config.py
git commit -m "feat(operator): config persistante validee (societe, TVA, compteur devis, regles tri)"
```

---

### Task 2: `operator/report.py` — journal d'activité

**Files:**
- Create: `jarvis_actions/operator/report.py`
- Test: `tests/test_operator_report.py`

**Interfaces:**
- Consumes: rien (broadcast injecté).
- Produces: `report.journaliser(evenement: dict) -> dict`, `report.derniers(n: int=50) -> list[dict]`, `report.resume_textuel(depuis: str|None=None) -> str`, `report.REPORT_PATH: Path`, `report.set_broadcast(cb)`.

- [ ] **Step 1: Tests (échouent)**

```python
# tests/test_operator_report.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def rep(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.report")
    monkeypatch.setattr(mod, "REPORT_PATH", tmp_path / "jarvis_operator_report.json")
    mod.set_broadcast(None)
    return mod

def test_journaliser_persiste_et_horodate(rep):
    ev = rep.journaliser({"type": "email_trie", "detail": "Facture EDF -> Factures"})
    assert ev["type"] == "email_trie"
    assert "ts" in ev and ev["ts"]
    assert len(rep.derniers()) == 1

def test_resume_compte_par_type(rep):
    rep.journaliser({"type": "email_trie", "detail": "a"})
    rep.journaliser({"type": "email_trie", "detail": "b"})
    rep.journaliser({"type": "email_archive", "detail": "c"})
    txt = rep.resume_textuel()
    assert "2" in txt and "email" in txt.lower()

def test_broadcast_appele(rep):
    recu = []
    rep.set_broadcast(lambda payload: recu.append(payload))
    rep.journaliser({"type": "rdv_cree", "detail": "x"})
    assert recu and recu[0]["action"] == "operator_activity"
```

- [ ] **Step 2: Lancer → échec.** Run: `python -m pytest tests/test_operator_report.py -q` → FAIL.

- [ ] **Step 3: Implémenter `report.py`**

```python
# jarvis_actions/operator/report.py
"""Journal d'activite de l'Operator : chaque action autonome (mail trie, RDV cree...)
est journalisee (persistee), diffusee aux clients (operator_activity), et resumable
en langage naturel ('voici ce que j'ai fait avec ta boite mail')."""
from __future__ import annotations
import json, os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config

REPORT_PATH: Path = config._dossier_donnees() / "jarvis_operator_report.json"
_MAX = 500
_broadcast: Callable[[dict], None] | None = None

def set_broadcast(cb: Callable[[dict], None] | None) -> None:
    global _broadcast
    _broadcast = cb

def _charger() -> list[dict]:
    if not REPORT_PATH.exists():
        return []
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _ecrire(items: list[dict]) -> None:
    try:
        tmp = REPORT_PATH.with_name(REPORT_PATH.name + ".tmp")
        tmp.write_text(json.dumps(items[-_MAX:], indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, REPORT_PATH)
    except Exception as e:
        print(f"[OPERATOR-REPORT] Ecriture echouee : {e}")

def journaliser(evenement: dict) -> dict:
    ev = {"type": str(evenement.get("type", "info")),
          "detail": str(evenement.get("detail", "")),
          "ts": datetime.now().isoformat(timespec="seconds")}
    items = _charger()
    items.append(ev)
    _ecrire(items)
    if _broadcast:
        try:
            _broadcast({"action": "operator_activity", "evenement": ev})
        except Exception:
            pass
    return ev

def derniers(n: int = 50) -> list[dict]:
    return _charger()[-n:]

def resume_textuel(depuis: str | None = None) -> str:
    items = _charger()
    if depuis:
        items = [e for e in items if e.get("ts", "") >= depuis]
    if not items:
        return "Rien a signaler pour le moment."
    cnt = Counter(e["type"] for e in items)
    morceaux = [f"{n} {t.replace('_', ' ')}" for t, n in cnt.most_common()]
    return "Voici ce que j'ai fait : " + ", ".join(morceaux) + "."
```

- [ ] **Step 4: Lancer → succès.** Run: `python -m pytest tests/test_operator_report.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis_actions/operator/report.py tests/test_operator_report.py
git commit -m "feat(operator): journal d'activite + resume + broadcast"
```

---

### Task 3: `operator/approvals.py` — file d'approbation

**Files:**
- Create: `jarvis_actions/operator/approvals.py`
- Test: `tests/test_operator_approvals.py`

**Interfaces:**
- Produces: `approvals.ajouter(action: dict) -> str` (renvoie id), `approvals.lister() -> list[dict]`, `approvals.get(id) -> dict|None`, `approvals.rejeter(id) -> bool`, `approvals.confirmer(id, executeurs: dict) -> tuple[str, bool]`, `approvals.plus_recente() -> dict|None`, `approvals.set_broadcast(cb)`, `approvals.APPROVALS_PATH`. Types d'action : `send_devis`, `send_email_reply`.

- [ ] **Step 1: Tests (échouent)**

```python
# tests/test_operator_approvals.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def ap(monkeypatch, tmp_path):
    mod = importlib.import_module("jarvis_actions.operator.approvals")
    monkeypatch.setattr(mod, "APPROVALS_PATH", tmp_path / "jarvis_operator_approvals.json")
    mod.set_broadcast(None)
    return mod

def test_ajouter_genere_id_et_persiste(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "Devis ACME 1200 EUR", "payload": {"x": 1}})
    assert aid
    items = ap.lister()
    assert len(items) == 1 and items[0]["id"] == aid and items[0]["type"] == "send_devis"

def test_plus_recente(ap):
    ap.ajouter({"type": "send_email_reply", "resume": "r1", "payload": {}})
    a2 = ap.ajouter({"type": "send_devis", "resume": "r2", "payload": {}})
    assert ap.plus_recente()["id"] == a2

def test_rejeter_retire(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "x", "payload": {}})
    assert ap.rejeter(aid) is True
    assert ap.lister() == []
    assert ap.rejeter("inexistant") is False

@pytest.mark.asyncio
async def test_confirmer_appelle_executeur_et_retire(ap):
    aid = ap.ajouter({"type": "send_devis", "resume": "x", "payload": {"client": "ACME"}})
    appels = []
    async def faux_envoi(payload):
        appels.append(payload)
        return "Devis envoye a ACME.", True
    msg, ok = await ap.confirmer(aid, {"send_devis": faux_envoi})
    assert ok is True and "ACME" in msg
    assert appels and appels[0]["client"] == "ACME"
    assert ap.lister() == []  # retiree apres execution reussie

@pytest.mark.asyncio
async def test_confirmer_type_inconnu(ap):
    aid = ap.ajouter({"type": "mystere", "resume": "x", "payload": {}})
    msg, ok = await ap.confirmer(aid, {})
    assert ok is False
    assert ap.get(aid) is not None  # conservee si echec
```

- [ ] **Step 2: Lancer → échec.** `python -m pytest tests/test_operator_approvals.py -q` → FAIL.

- [ ] **Step 3: Implémenter `approvals.py`**

```python
# jarvis_actions/operator/approvals.py
"""File d'approbation de l'Operator : aucune action sortante (devis/email) n'est
executee sans un 'oui' explicite. Persistee, diffusee a tous les clients
(operator_pending). confirmer() delegue a un executeur fourni par main2."""
from __future__ import annotations
import json, os, uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import config

APPROVALS_PATH: Path = config._dossier_donnees() / "jarvis_operator_approvals.json"
TYPES = ("send_devis", "send_email_reply")
_broadcast: Callable[[dict], None] | None = None

def set_broadcast(cb: Callable[[dict], None] | None) -> None:
    global _broadcast
    _broadcast = cb

def _charger() -> list[dict]:
    if not APPROVALS_PATH.exists():
        return []
    try:
        data = json.loads(APPROVALS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _ecrire(items: list[dict]) -> None:
    try:
        tmp = APPROVALS_PATH.with_name(APPROVALS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, APPROVALS_PATH)
    except Exception as e:
        print(f"[OPERATOR-APPROVALS] Ecriture echouee : {e}")

def _diffuser() -> None:
    if _broadcast:
        try:
            _broadcast({"action": "operator_pending", "pending": lister()})
        except Exception:
            pass

def ajouter(action: dict) -> str:
    aid = uuid.uuid4().hex[:12]
    item = {"id": aid, "type": str(action.get("type", "")),
            "resume": str(action.get("resume", "")),
            "payload": action.get("payload", {}) if isinstance(action.get("payload"), dict) else {},
            "ts": datetime.now().isoformat(timespec="seconds")}
    items = _charger()
    items.append(item)
    _ecrire(items)
    _diffuser()
    return aid

def lister() -> list[dict]:
    return _charger()

def get(aid: str) -> dict | None:
    return next((i for i in _charger() if i["id"] == aid), None)

def plus_recente() -> dict | None:
    items = _charger()
    return items[-1] if items else None

def rejeter(aid: str) -> bool:
    items = _charger()
    restant = [i for i in items if i["id"] != aid]
    if len(restant) == len(items):
        return False
    _ecrire(restant)
    _diffuser()
    return True

async def confirmer(aid: str, executeurs: dict[str, Callable[[dict], Awaitable[tuple[str, bool]]]]) -> tuple[str, bool]:
    item = get(aid)
    if not item:
        return "Aucune action en attente avec cet identifiant.", False
    ex = executeurs.get(item["type"])
    if ex is None:
        return f"Type d'action non gere : {item['type']}.", False
    try:
        msg, ok = await ex(item["payload"])
    except Exception as e:
        return f"Echec de l'envoi : {e}", False
    if ok:
        rejeter(aid)  # retire + diffuse
    return msg, ok
```

- [ ] **Step 4: Lancer → succès.** `python -m pytest tests/test_operator_approvals.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis_actions/operator/approvals.py tests/test_operator_approvals.py
git commit -m "feat(operator): file d'approbation persistee (devis/email) + confirmer/rejeter"
```

---

### Task 4: `operator/__init__.py` — façade + routeur vocal pur

**Files:**
- Modify: `jarvis_actions/operator/__init__.py`
- Test: `tests/test_operator_router.py`

**Interfaces:**
- Consumes: `config`, `report`, `approvals`.
- Produces: `operator.init(ctx: dict) -> None`, `operator._router(texte: str, a_des_approbations: bool) -> tuple[str, dict]|None` (PUR : renvoie `(intention, params)` ou None), `operator.async_executer(cmd: str) -> tuple[str|None, bool]`, `operator.tools() -> list` (stub `[]`), `operator.dispatch(name, args) -> str` (stub), `operator.demarrer_planificateur() -> None` (stub coroutine).
- `ctx` keys attendues (injectées en Phase 2-6, tolérées absentes) : `get_gmail_service, get_calendar_service, get_docs_service, demander_ia, demander_json, parler, broadcast_ws, user_name`.

- [ ] **Step 1: Tests du routeur PUR (échouent)**

```python
# tests/test_operator_router.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def op():
    return importlib.import_module("jarvis_actions.operator")

@pytest.mark.parametrize("phrase, intent", [
    ("trie mes mails", "email_triage"),
    ("occupe-toi de mes mails", "email_triage"),
    ("ecoute la reunion", "meeting_start"),
    ("arrete d'ecouter", "meeting_stop"),
    ("fais un devis", "devis_new"),
    ("prepare le devis", "devis_new"),
    ("prends un rdv mardi 14h", "rdv_new"),
    ("ajoute a mon agenda demain 9h dentiste", "rdv_new"),
    ("fais une recherche sur les prix du carrelage", "research"),
    ("recherche approfondie sur la TVA chantier", "research"),
])
def test_router_intentions(op, phrase, intent):
    res = op._router(phrase, a_des_approbations=False)
    assert res is not None and res[0] == intent

def test_oui_non_ignores_sans_approbation(op):
    assert op._router("oui", a_des_approbations=False) is None
    assert op._router("non", a_des_approbations=False) is None

def test_oui_non_captures_avec_approbation(op):
    assert op._router("oui", a_des_approbations=True)[0] == "approve_confirm"
    assert op._router("envoie", a_des_approbations=True)[0] == "approve_confirm"
    assert op._router("annule", a_des_approbations=True)[0] == "approve_reject"

def test_non_pertinent_renvoie_none(op):
    assert op._router("quelle heure est-il", a_des_approbations=True) is None
```

- [ ] **Step 2: Lancer → échec.** `python -m pytest tests/test_operator_router.py -q` → FAIL.

- [ ] **Step 3: Implémenter la façade + `_router`**

```python
# jarvis_actions/operator/__init__.py
"""Sous-systeme Operator de Jarvis : tri mail, RDV/agenda, reunion, devis, recherche.
Facade publique : init(ctx), async_executer (voix), tools()/dispatch() (agent Gemini),
demarrer_planificateur() (tri mail de fond). Le routeur _router est PUR et teste."""
from __future__ import annotations
import re
from typing import Any, Callable

from . import config, report, approvals

_CTX: dict[str, Any] = {}

def init(ctx: dict[str, Any]) -> None:
    """Injecte les dependances de main2 (services Google, LLM, parler, broadcast).
    Cable les broadcasts de report/approvals sur le broadcast WS fourni."""
    global _CTX
    _CTX = dict(ctx or {})
    bc = _CTX.get("broadcast_ws")
    if bc:
        report.set_broadcast(bc)
        approvals.set_broadcast(bc)

# --- Routeur vocal PUR : texte -> (intention, params) | None ---
_REGLES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(trie|tri)\b.*\bmails?\b"), "email_triage"),
    (re.compile(r"\boccupe[- ]toi\b.*\bmails?\b"), "email_triage"),
    (re.compile(r"\b(arr[eê]te d'?[eé]couter|stop r[eé]union|fini la r[eé]union)\b"), "meeting_stop"),
    (re.compile(r"\b[eé]coute(r)?\b.*\b(r[eé]union|conversation)\b"), "meeting_start"),
    (re.compile(r"\b(fais|pr[eé]pare|cr[eé]e)\b.*\bdevis\b"), "devis_new"),
    (re.compile(r"\b(prends?|ajoute|cr[eé]e|planifie)\b.*\b(rdv|rendez[- ]vous|agenda)\b"), "rdv_new"),
    (re.compile(r"\brecherche approfondie\b"), "research"),
    (re.compile(r"\b(fais|lance)\b.*\brecherche(s)?\b"), "research"),
    (re.compile(r"\brecherche\b.*\b(sur internet|en ligne)\b"), "research"),
]
_CONFIRM = re.compile(r"^\s*(oui|ok|d'?accord|valide|envoie|envoyer|confirme)\b", re.I)
_REJECT = re.compile(r"^\s*(non|annule|annuler|refuse|rejette|laisse tomber)\b", re.I)

def _router(texte: str, a_des_approbations: bool) -> tuple[str, dict] | None:
    t = (texte or "").strip().lower()
    if not t:
        return None
    if a_des_approbations:
        if _CONFIRM.search(t):
            return ("approve_confirm", {})
        if _REJECT.search(t):
            return ("approve_reject", {})
    for pat, intent in _REGLES:
        if pat.search(t):
            return (intent, {"texte": texte})
    return None

async def async_executer(cmd: str) -> tuple[str | None, bool]:
    """Point d'entree voix. Renvoie (None, False) si non gere (chaine continue)."""
    a_pending = bool(approvals.lister())
    routed = _router(cmd, a_pending)
    if routed is None:
        return None, False
    intent, params = routed
    try:
        return await _executer_intent(intent, params)
    except Exception as e:
        return f"Erreur Operator : {e}", False

async def _executer_intent(intent: str, params: dict) -> tuple[str | None, bool]:
    # Implementations branchees au fil des phases. Par defaut : message d'attente.
    if intent == "approve_confirm":
        return await _confirmer_derniere()
    if intent == "approve_reject":
        rec = approvals.plus_recente()
        if rec and approvals.rejeter(rec["id"]):
            return "Tres bien, j'annule.", True
        return "Il n'y a rien a annuler.", True
    return f"La fonction '{intent}' n'est pas encore disponible.", True

async def _confirmer_derniere() -> tuple[str | None, bool]:
    rec = approvals.plus_recente()
    if not rec:
        return "Il n'y a rien a valider.", True
    return await approvals.confirmer(rec["id"], _executeurs_approbation())

def _executeurs_approbation() -> dict[str, Callable]:
    """Map type d'approbation -> coroutine d'execution. Rempli en Phase 2/5."""
    return {}

def tools() -> list:
    """FunctionDeclarations Gemini (rempli en Phase 6)."""
    return []

async def dispatch(name: str, args: dict) -> str:
    """Dispatch des outils Gemini de l'Operator (rempli en Phase 6)."""
    return ""

async def demarrer_planificateur() -> None:
    """Boucle de tri mail de fond (implementee en Phase 2)."""
    return None
```

- [ ] **Step 4: Lancer → succès.** `python -m pytest tests/test_operator_router.py -q` → PASS.

- [ ] **Step 5: Suite complète Operator verte.** `python -m pytest tests/test_operator_*.py -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add jarvis_actions/operator/__init__.py tests/test_operator_router.py
git commit -m "feat(operator): facade + routeur vocal pur + garde approbation oui/non"
```

---

### Task 5: Wiring `main2.py` (import, init, dispatch, scheduler)

**Files:**
- Modify: `jarvis_core/main2.py` (import operator ; appel `operator.init(...)` après les getters Google ; bloc dispatch dans `traiter_reponse_ia` après le bloc `browser` ; `asyncio.create_task(operator.demarrer_planificateur())` dans `start_ia` à côté de `routines`).

**Interfaces:**
- Consumes: `operator.init`, `operator.async_executer`, `operator.demarrer_planificateur` (Task 4).

- [ ] **Step 1: Import (suivre le pattern try/except des autres modules d'actions)** — près des imports `jarvis_actions` existants :

```python
try:
    from jarvis_actions import operator as jarvis_operator
except Exception as _e:
    jarvis_operator = None
    print(f"[OPERATOR] indisponible : {_e}")
```

- [ ] **Step 2: `operator.init(...)`** — après la définition de `get_gmail_service`/`get_calendar_service`/`get_docs_service` et de `demander_ia`/`parler`. Trouver un point d'init centralisé (là où MCP/routines sont initialisés). Ajouter :

```python
if jarvis_operator:
    async def _operator_demander_json(prompt: str) -> str:
        # reutilise la chaine IA existante en mode texte
        return await demander_ia(prompt)
    jarvis_operator.init({
        "get_gmail_service": get_gmail_service,
        "get_calendar_service": get_calendar_service,
        "get_docs_service": get_docs_service,
        "demander_ia": demander_ia,
        "demander_json": _operator_demander_json,
        "parler": parler,
        "broadcast_ws": lambda payload: asyncio.create_task(_broadcast(payload)),
        "user_name": USER_NAME,
    })
```

> NOTE pour l'implémenteur : repérer le nom exact de la fonction de broadcast WS (chercher `CONNECTED_CLIENTS` et la fonction qui `send` à tous). L'adapter ici. Si `demander_ia` n'est pas `async`, wrapper avec `asyncio.to_thread`.

- [ ] **Step 3: Bloc dispatch dans `traiter_reponse_ia`** — juste APRÈS le bloc `jarvis_browser.async_executer` (vers la ligne ~3509) et AVANT `skills` :

```python
        # --- OPERATOR (tri mail, RDV, reunion, devis, recherche, approbations) ---
        if jarvis_operator:
            op_rep, op_ok = await jarvis_operator.async_executer(cmd)
            if op_rep is not None:
                if repondre_vocal:
                    await parler(op_rep)
                return op_rep
```

> Placement justifié : après `browser` (« cherche X sur google » reste au navigateur), avant skills/pc — les verbes Operator (« trie mes mails », « fais un devis ») sont spécifiques et ne collisionnent pas avec l'ouverture d'apps.

- [ ] **Step 4: Scheduler dans `start_ia`** — à côté de `asyncio.create_task(routines.demarrer_planificateur(...))` :

```python
    if jarvis_operator:
        asyncio.create_task(jarvis_operator.demarrer_planificateur())
```

- [ ] **Step 5: Vérification d'import (smoke)**

Run: `python -c "import sys; sys.path.insert(0,'jarvis_core'); sys.path.insert(0,'.'); import jarvis_actions.operator as o; print('ok', bool(o))"`
Expected: `ok True`

- [ ] **Step 6: Suite pytest complète inchangée (pas de régression)**

Run: `python -m pytest -q`
Expected: PASS (158 + nouveaux tests).

- [ ] **Step 7: Commit**

```bash
git add jarvis_core/main2.py
git commit -m "feat(operator): wiring main2 (init, dispatch vocal, scheduler de fond)"
```

---

### Task 6: Coquille onglet « Operator » (dashboard)

**Files:**
- Create: `frontend/src/dashboard/sections_operator.ts`
- Modify: `frontend/src/dashboard/sections.ts` (import + ajout à `SECTIONS` + à `MAIN_SECTION_IDS`)
- Modify: `jarvis_core/jarvis_dashboard_api.py` (handlers `dash_operator_init` / `dash_operator_activity_get` + enregistrement dans `_HANDLERS` ; callables injectés via `init_api`)

**Interfaces:**
- Consumes: `report.derniers`, `approvals.lister` (via `init_api` context).
- Produces: messages WS `dash_operator_init` → `dash_operator_state` (état : pending + activité), socle pour les sous-panneaux des phases suivantes.

- [ ] **Step 1: Handler backend** — dans `jarvis_dashboard_api.py`, ajouter (les callables Operator sont passés à `init_api` ; à défaut, importer directement `from jarvis_actions.operator import report as op_report, approvals as op_approvals`) :

```python
async def _h_operator_init(data: dict) -> dict:
    try:
        from jarvis_actions.operator import report as op_report, approvals as op_approvals
        return {"action": "dash_operator_state",
                "pending": op_approvals.lister(),
                "activity": op_report.derniers(50)}
    except Exception as e:
        return {"action": "dash_operator_state", "pending": [], "activity": [], "error": str(e)}

async def _h_operator_confirm(data: dict) -> dict:
    # confirmation depuis le dashboard : delegue a la facade operator
    from jarvis_actions.operator import approvals as op_approvals
    aid = str(data.get("id", ""))
    # NOTE Phase 2/5 : brancher les vrais executeurs ; ici socle
    ok = op_approvals.rejeter(aid)  # placeholder remplace en Phase 5 par confirmer()
    return {"action": "dash_operator_pending", "pending": op_approvals.lister(), "ok": ok}
```

Enregistrer dans `_HANDLERS` :

```python
    "dash_operator_init": _h_operator_init,
    "dash_operator_confirm": _h_operator_confirm,
```

> En Phase 5, `_h_operator_confirm` appellera `operator.confirmer_depuis_dashboard(aid)` (coroutine de la façade qui utilise les vrais exécuteurs). Le socle ici se contente de lister/rejeter.

- [ ] **Step 2: Section frontend** — `sections_operator.ts` (calqué sur `sections_code.ts`) :

```typescript
import type { Section } from "./sections";
import * as ws from "./ws";

export const sectionOperator: Section = {
  id: "operator",
  label: "Operator",
  icon: "🛰️",
  mount(root: HTMLElement) {
    root.innerHTML = `
      <h2>Operator</h2>
      <section class="op-pending"><h3>À valider</h3><div class="op-pending-list">Aucune action en attente.</div></section>
      <section class="op-activity"><h3>Activité récente</h3><div class="op-activity-list">—</div></section>
    `;
    const pendingList = root.querySelector(".op-pending-list") as HTMLElement;
    const activityList = root.querySelector(".op-activity-list") as HTMLElement;

    const renderPending = (items: any[]) => {
      pendingList.innerHTML = items.length
        ? items.map((i) => `<div class="op-item"><span>${i.resume ?? i.type}</span>
            <button data-confirm="${i.id}">Valider</button>
            <button data-reject="${i.id}">Rejeter</button></div>`).join("")
        : "Aucune action en attente.";
      pendingList.querySelectorAll("[data-confirm]").forEach((b) =>
        b.addEventListener("click", () => ws.send({ type: "dash_operator_confirm", id: (b as HTMLElement).dataset.confirm })));
      pendingList.querySelectorAll("[data-reject]").forEach((b) =>
        b.addEventListener("click", () => ws.send({ type: "dash_operator_reject", id: (b as HTMLElement).dataset.reject })));
    };
    const renderActivity = (items: any[]) => {
      activityList.innerHTML = items.length
        ? items.slice().reverse().map((e) => `<div class="op-log">[${e.ts ?? ""}] ${e.type}: ${e.detail ?? ""}</div>`).join("")
        : "—";
    };

    const offState = ws.on("dash_operator_state", (m: any) => { renderPending(m.pending ?? []); renderActivity(m.activity ?? []); });
    const offPending = ws.on("dash_operator_pending", (m: any) => renderPending(m.pending ?? []));
    const offActivity = ws.on("operator_activity", (_m: any) => ws.send({ type: "dash_operator_init" }));

    ws.send({ type: "dash_operator_init" });
    return () => { offState(); offPending(); offActivity(); };
  },
};
```

- [ ] **Step 3: Enregistrer la section** — dans `sections.ts` : importer `sectionOperator`, l'ajouter au tableau `SECTIONS`, et ajouter `"operator"` à `MAIN_SECTION_IDS` (onglet principal, en tête ou après `chat`).

- [ ] **Step 4: Build frontend (vérif compilation)**

Run: `cd frontend && npx vite build`
Expected: build OK, pas d'erreur TS bloquante.

- [ ] **Step 5: Vérif manuelle** — `python jarvis_core/main2.py`, ouvrir `http://localhost:5173/dashboard.html`, onglet « Operator » s'affiche (listes vides). 

- [ ] **Step 6: Commit**

```bash
git add frontend/src/dashboard/sections_operator.ts frontend/src/dashboard/sections.ts jarvis_core/jarvis_dashboard_api.py
git commit -m "feat(operator): onglet dashboard (socle pending + activite)"
```

---

# PHASE 2 — Tri email + scheduler + brouillons + approbation

### Task 7: Scope Gmail `gmail.modify`

**Files:** Modify: `jarvis_core/main2.py` (`SCOPES`, ~ligne 1289).

- [ ] **Step 1:** Remplacer `"https://www.googleapis.com/auth/gmail.readonly"` par `"https://www.googleapis.com/auth/gmail.modify"` (modify englobe readonly + labels + archive). Garder `gmail.send`.
- [ ] **Step 2:** Ajouter un commentaire : `# gmail.modify : requis pour etiqueter/archiver (Operator). Re-consentement OAuth au prochain run.`
- [ ] **Step 3: Commit** `git commit -am "feat(operator): scope gmail.modify (etiquetage/archivage)"`

---

### Task 8: `operator/prompts.py` + `operator/gmail_ops.py` (helpers purs)

**Files:**
- Create: `jarvis_actions/operator/prompts.py`
- Create: `jarvis_actions/operator/gmail_ops.py`
- Test: `tests/test_operator_gmail.py`

**Interfaces:**
- Produces:
  - `prompts.classif_email(expediteur, sujet, extrait) -> str` (gabarit pur)
  - `gmail_ops.parser_classif(texte_llm) -> dict` (extrait `{categorie, priorite, besoin_reponse, action}` d'une sortie LLM bruitée, défensif comme `memory_proactive._extraire_bloc_json`)
  - `gmail_ops.decider_action(classif, regles) -> dict` (PUR : applique les `regles_tri` de la config → `{label, archiver, brouillon}`)
  - `gmail_ops.extraire_entetes(message) -> dict` (From/Subject/snippet depuis un message Gmail brut)

- [ ] **Step 1: Tests purs (échouent)**

```python
# tests/test_operator_gmail.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def g():
    return importlib.import_module("jarvis_actions.operator.gmail_ops")

def test_parser_classif_json_propre(g):
    out = g.parser_classif('{"categorie": "Facture", "priorite": "haute", "besoin_reponse": true}')
    assert out["categorie"] == "Facture" and out["besoin_reponse"] is True

def test_parser_classif_bruite(g):
    txt = "Voici l'analyse: {\"categorie\":\"Spam\",\"priorite\":\"basse\",\"besoin_reponse\":false} merci"
    out = g.parser_classif(txt)
    assert out["categorie"] == "Spam" and out["besoin_reponse"] is False

def test_parser_classif_invalide_renvoie_defaut(g):
    out = g.parser_classif("pas de json ici")
    assert out["categorie"] == "Autre" and out["besoin_reponse"] is False

def test_decider_action_regle_match(g):
    classif = {"categorie": "Facture", "besoin_reponse": False}
    regles = [{"si_contient": "facture", "label": "Factures", "archiver": True}]
    act = g.decider_action(classif, regles)
    assert act["label"] == "Factures" and act["archiver"] is True

def test_decider_action_brouillon_si_besoin_reponse(g):
    act = g.decider_action({"categorie": "Client", "besoin_reponse": True}, [])
    assert act["brouillon"] is True

def test_extraire_entetes(g):
    msg = {"payload": {"headers": [{"name": "From", "value": "a@b.com"},
                                    {"name": "Subject", "value": "Bonjour"}]},
           "snippet": "Ceci est un extrait"}
    e = g.extraire_entetes(msg)
    assert e["from"] == "a@b.com" and e["sujet"] == "Bonjour" and "extrait" in e["extrait"]
```

- [ ] **Step 2: Lancer → échec.** `python -m pytest tests/test_operator_gmail.py -q` → FAIL.

- [ ] **Step 3: Implémenter `prompts.py` (classif_email) puis `gmail_ops.py`** (helpers purs + appels Gmail isolés). Détails clés :
  - `parser_classif` : réutiliser la logique défensive de `memory_proactive` (extraire le premier bloc `{...}`, `json.loads`, fallback `{"categorie":"Autre","priorite":"normale","besoin_reponse":False}`).
  - `decider_action(classif, regles)` PUR : parcourir `regles_tri` ; si `si_contient` ∈ catégorie/sujet → `label`/`archiver` ; `brouillon = bool(classif.get("besoin_reponse"))`.
  - Fonctions à effets isolés (testées via mocks d'intégration plus tard, pas en unitaire pur) : `lister_threads_non_lus(service, n)`, `appliquer_label(service, msg_id, label)`, `archiver(service, msg_id)`, `creer_brouillon(service, thread_id, corps)` (utilise `service.users().drafts().create`), `assurer_label(service, nom) -> label_id`.

- [ ] **Step 4: Lancer → succès.** `python -m pytest tests/test_operator_gmail.py -q` → PASS (6 tests).

- [ ] **Step 5: Commit** `git add ... && git commit -m "feat(operator): classification email + decision de tri (helpers purs)"`

---

### Task 9: Boucle de tri (scheduler) + report + approbation des brouillons

**Files:**
- Modify: `jarvis_actions/operator/__init__.py` (`demarrer_planificateur`, `_executer_intent` cas `email_triage`, `_executeurs_approbation` cas `send_email_reply`, helper `_trier_mails()`)
- Test: ajout dans `tests/test_operator_gmail.py` (test d'orchestration avec service Gmail mocké + `demander_json` mocké)

**Interfaces:**
- Consumes: `gmail_ops`, `report`, `approvals`, `_CTX["get_gmail_service"]`, `_CTX["demander_json"]`, `config`.
- Produces: `operator._trier_mails() -> tuple[str, bool]` (résumé), `demarrer_planificateur` qui appelle `_trier_mails` toutes `triage_intervalle_min`.

- [ ] **Step 1: Test d'orchestration (échoue)** — un faux service Gmail (objet avec `.users().messages().list/get`, `.users().drafts().create`) + `demander_json` renvoyant un JSON de classif. Vérifier que `_trier_mails()` journalise et crée une approbation `send_email_reply` quand `besoin_reponse=True`. Injecter via `operator.init({...})` avec les mocks + `monkeypatch` des PATHs de report/approvals/config vers `tmp_path`.

```python
@pytest.mark.asyncio
async def test_trier_mails_cree_brouillon_et_journalise(monkeypatch, tmp_path):
    import importlib
    op = importlib.import_module("jarvis_actions.operator")
    cfg = importlib.import_module("jarvis_actions.operator.config")
    rep = importlib.import_module("jarvis_actions.operator.report")
    ap = importlib.import_module("jarvis_actions.operator.approvals")
    monkeypatch.setattr(cfg, "OPERATOR_PATH", tmp_path / "op.json")
    monkeypatch.setattr(rep, "REPORT_PATH", tmp_path / "rep.json")
    monkeypatch.setattr(ap, "APPROVALS_PATH", tmp_path / "ap.json")

    class FakeMessages:
        def list(self, **k): return self
        def get(self, **k): return self
        def execute(self):
            return {"messages": [{"id": "m1", "threadId": "t1"}]} if not hasattr(self, "_g") else {
                "payload": {"headers": [{"name": "From", "value": "client@x.com"},
                                         {"name": "Subject", "value": "Demande de devis"}]},
                "snippet": "Bonjour, pouvez-vous me faire un devis ?"}
    # ... (faux service complet : users().messages()/drafts())
    async def fake_json(prompt):
        return '{"categorie":"Client","priorite":"haute","besoin_reponse":true}'
    op.init({"get_gmail_service": lambda: FAKE_SERVICE, "demander_json": fake_json,
             "broadcast_ws": None, "user_name": "Monsieur"})
    msg, ok = await op._trier_mails()
    assert ok is True
    assert any(a["type"] == "send_email_reply" for a in ap.lister())
    assert rep.derniers()  # au moins un evenement
```

> L'implémenteur complétera le faux service (pattern objet chainable `list().execute()`). Garder le test hermétique (aucun réseau).

- [ ] **Step 2: Lancer → échec.**

- [ ] **Step 3: Implémenter `_trier_mails`** : récupérer service ; lister N threads non lus ; pour chacun : extraire entêtes → `demander_json(prompts.classif_email(...))` → `parser_classif` → `decider_action(classif, config.charger()["regles_tri"])` → appliquer label/archive si autonomie ≠ `tout_en_validation` → si `brouillon` : générer un corps de réponse (LLM) + `gmail_ops.creer_brouillon` + `approvals.ajouter({"type":"send_email_reply", "resume": ..., "payload": {"draft_id"/"thread_id"/"corps"}})` → `report.journaliser`. Respecter `autonomie_email` (`tri_auto_seul` = pas de brouillon ; `autonomie_totale` = envoi direct sans approbation). Renvoyer le `report.resume_textuel(depuis=...)`.

  `demarrer_planificateur` :

```python
async def demarrer_planificateur() -> None:
    import asyncio
    while True:
        try:
            intervalle = max(1, int(config.charger().get("triage_intervalle_min", 15)))
        except Exception:
            intervalle = 15
        await asyncio.sleep(intervalle * 60)
        if _CTX.get("get_gmail_service"):
            try:
                await _trier_mails()
            except Exception as e:
                print(f"[OPERATOR] tri auto echoue : {e}")
```

  `_executer_intent` cas `email_triage` → `return await _trier_mails()`.
  `_executeurs_approbation` cas `send_email_reply` → coroutine qui envoie le brouillon via Gmail `users().drafts().send` (ou `messages().send`).

- [ ] **Step 4: Lancer → succès.** `python -m pytest tests/test_operator_gmail.py -q` → PASS.
- [ ] **Step 5: Suite complète.** `python -m pytest -q` → PASS.
- [ ] **Step 6: Commit** `git commit -am "feat(operator): tri mail de fond + brouillons soumis a validation + rapport"`

---

# PHASE 3 — Agenda / RDV

### Task 10: `operator/calendar_ops.py` (helpers purs) + parsing RDV

**Files:**
- Create: `jarvis_actions/operator/calendar_ops.py`
- Modify: `jarvis_actions/operator/prompts.py` (`parse_rdv`)
- Test: `tests/test_operator_calendar.py`

**Interfaces:**
- Produces:
  - `calendar_ops.parser_rdv_json(texte_llm) -> dict|None` (défensif → `{titre, debut_iso, fin_iso, lieu, invites}`)
  - `calendar_ops.construire_event(payload) -> dict` (PUR : payload → corps API Google Calendar `{summary, start, end, ...}`)
  - `calendar_ops.creneaux_libres(events, plage, duree_min) -> list[dict]` (PUR : à partir d'une liste d'events occupés + plage horaire, renvoie les trous)
  - effets isolés : `lister(service, debut, fin)`, `creer(service, payload)`, `supprimer(service, event_id)`.

- [ ] **Step 1: Tests purs (échouent)** — `construire_event` (mapping correct, durée par défaut 1h si pas de fin), `creneaux_libres` (cas : journée vide → 1 grand créneau ; 1 event au milieu → 2 créneaux ; chevauchement bord), `parser_rdv_json` (json propre/bruité/invalide).

```python
def test_construire_event_duree_defaut(c):
    ev = c.construire_event({"titre": "Dentiste", "debut_iso": "2026-07-01T09:00:00", "fin_iso": ""})
    assert ev["summary"] == "Dentiste"
    assert ev["start"]["dateTime"].startswith("2026-07-01T09:00")
    assert ev["end"]["dateTime"].startswith("2026-07-01T10:00")  # +1h

def test_creneaux_libres_journee_vide(c):
    libres = c.creneaux_libres([], {"debut": "09:00", "fin": "12:00", "date": "2026-07-01"}, 30)
    assert len(libres) == 1 and libres[0]["debut"].endswith("09:00:00")
```

- [ ] **Step 2-4:** échec → implémenter (`construire_event`, `creneaux_libres` pur, `parser_rdv_json` défensif ; `lister/creer/supprimer` isolés) → succès.
- [ ] **Step 5: Commit** `git commit -m "feat(operator): calendar_ops (construire event, creneaux libres, parse RDV)"`

---

### Task 11: Intent `rdv_new` + panneau Agenda

**Files:**
- Modify: `jarvis_actions/operator/__init__.py` (`_executer_intent` cas `rdv_new` → `parser_rdv` (LLM) → `creneaux_libres`/`creer` → `report.journaliser` → message vocal de confirmation)
- Modify: `frontend/src/dashboard/sections_operator.ts` (sous-panneau Agenda : prochains événements + bouton « ajouter »)
- Modify: `jarvis_core/jarvis_dashboard_api.py` (`dash_operator_agenda_get` → events via `calendar_ops.lister`)
- Test: ajout `tests/test_operator_calendar.py` (intent `rdv_new` avec service + LLM mockés)

- [ ] **Step 1: Test orchestration `rdv_new`** (échoue) → **Step 2** échec → **Step 3** implémenter → **Step 4** succès.
- [ ] **Step 5:** Build frontend OK. **Step 6: Commit** `git commit -m "feat(operator): creation RDV vocale + panneau agenda"`

---

# PHASE 4 — Réunion (live + import) + résumé

### Task 12: `operator/meeting.py` — transcription fichier + résumé

**Files:**
- Create: `jarvis_actions/operator/meeting.py`
- Modify: `jarvis_actions/operator/prompts.py` (`resume_reunion`)
- Test: `tests/test_operator_meeting.py`

**Interfaces:**
- Produces:
  - `meeting.transcrire_fichier(path) -> str` (réutilise faster-whisper de `voice_stt` ; dégrade si absent → `""` + message)
  - `meeting.resumer(transcript, demander_ia) -> str`
  - `meeting.etat() -> dict` (`{actif: bool, transcript: str}`)
  - `meeting.demarrer(capture, broadcast)` / `meeting.arreter() -> str` (live, Task 13)
  - `meeting.disponible() -> bool` (faster-whisper importable)

- [ ] **Step 1: Tests (échouent)** — `disponible()` reflète la présence de faster-whisper (monkeypatch) ; `resumer` appelle `demander_ia` avec le transcript et renvoie son retour (LLM mické) ; `transcrire_fichier` sur fichier inexistant → `""` sans exception.

```python
@pytest.mark.asyncio
async def test_resumer_appelle_llm(m):
    async def fake_ia(prompt): return "Resume: devis carrelage 50m2."
    out = await m.resumer("transcript brut...", fake_ia)
    assert "devis" in out.lower()

def test_transcrire_fichier_absent(m):
    assert m.transcrire_fichier("/n/existe/pas.wav") == ""
```

- [ ] **Step 2-4:** échec → implémenter (réutiliser `voice_stt._charger_whisper`/API ; pour un fichier, `WhisperModel.transcribe(path)`) → succès.
- [ ] **Step 5: Commit** `git commit -m "feat(operator): meeting transcription fichier + resume"`

---

### Task 13: Mode réunion LIVE + panneau Réunion (dashboard) + import

**Files:**
- Modify: `jarvis_actions/operator/meeting.py` (`demarrer`/`arreter` : boucle continue de capture micro → chunks transcrits → `broadcast({"action":"operator_transcript","chunk":...})`. Réutilise `speech_recognition` comme `ecouter()` mais SANS wake word, jusqu'à `arreter()`.)
- Modify: `jarvis_actions/operator/__init__.py` (`_executer_intent` cas `meeting_start`/`meeting_stop` ; à l'arrêt → `resumer` + proposer « générer un devis » via approbation/journal)
- Modify: `frontend/src/dashboard/sections_operator.ts` (panneau Réunion : Démarrer/Arrêter, transcript live streaming, zone d'import fichier audio → `dash_operator_meeting_import`)
- Modify: `jarvis_core/jarvis_dashboard_api.py` (`dash_operator_meeting_start/stop/import`)

- [ ] **Step 1:** Implémenter `demarrer/arreter` (thread de capture, flag `_actif`, accumulation transcript, broadcast chunks). État « écoute » visible : envoyer `send_web_state("listening")` ou un état dédié. **Vie privée** : start/stop explicite, transcript stocké localement uniquement.
- [ ] **Step 2:** Intents `meeting_start`/`meeting_stop` + handlers dashboard + import fichier (`meeting.transcrire_fichier`).
- [ ] **Step 3:** Build frontend OK ; vérif manuelle (démarrer/arrêter, transcript s'affiche).
- [ ] **Step 4: Tests** : `arreter()` renvoie le transcript accumulé (capture mockée) ; import fichier (whisper mocké).
- [ ] **Step 5: Commit** `git commit -m "feat(operator): mode reunion live + import audio + panneau dashboard"`

---

# PHASE 5 — Devis (modèle + PDF + extraction) + envoi

### Task 14: `operator/devis.py` — modèle + calculs purs

**Files:**
- Create: `jarvis_actions/operator/devis.py`
- Test: `tests/test_operator_devis.py`

**Interfaces:**
- Produces:
  - `devis.ligne(libelle, type, quantite, unite, pu_ht, tva_pct) -> dict` (normalisé, immuable)
  - `devis.calculer_totaux(lignes) -> dict` (PUR : `{total_ht, tva_par_taux: {20.0: x}, total_tva, total_ttc}`, arrondi 2 décimales)
  - `devis.numero_suivant(config_devis) -> str` (`DEV-2026-0001`)
  - `devis.construire(client, lignes, config) -> dict` (devis complet : numéro, date, validité, totaux, société)

- [ ] **Step 1: Tests purs (échouent)** — cœur de la valeur, TDD strict :

```python
# tests/test_operator_devis.py
from __future__ import annotations
import importlib
import pytest

@pytest.fixture
def d():
    return importlib.import_module("jarvis_actions.operator.devis")

def test_ligne_normalise(d):
    l = d.ligne("Pose carrelage", "prestation", 50, "m2", 30.0, 20.0)
    assert l["total_ht"] == 1500.0 and l["tva_pct"] == 20.0

def test_calculer_totaux_mono_taux(d):
    lignes = [d.ligne("A", "produit", 2, "u", 100.0, 20.0)]
    t = d.calculer_totaux(lignes)
    assert t["total_ht"] == 200.0
    assert t["tva_par_taux"][20.0] == 40.0
    assert t["total_ttc"] == 240.0

def test_calculer_totaux_multi_taux(d):
    lignes = [d.ligne("Main d'oeuvre", "prestation", 10, "h", 50.0, 10.0),
              d.ligne("Materiaux", "materiau", 1, "forfait", 200.0, 20.0)]
    t = d.calculer_totaux(lignes)
    assert t["total_ht"] == 700.0
    assert t["tva_par_taux"][10.0] == 50.0
    assert t["tva_par_taux"][20.0] == 40.0
    assert t["total_tva"] == 90.0
    assert t["total_ttc"] == 790.0

def test_calculer_totaux_arrondi(d):
    lignes = [d.ligne("X", "produit", 3, "u", 9.99, 20.0)]
    t = d.calculer_totaux(lignes)
    assert t["total_ht"] == 29.97
    assert t["total_ttc"] == 35.96  # 29.97 * 1.2 = 35.964 -> 35.96

def test_numero_suivant(d):
    assert d.numero_suivant({"prefixe": "DEV", "compteur": 41}).endswith("0042")
```

- [ ] **Step 2: Lancer → échec.**
- [ ] **Step 3: Implémenter `devis.py`** (calculs purs, `round(x, 2)`, regrouper TVA par taux, numéro `f"{prefixe}-{annee}-{compteur+1:04d}"` — l'année via `datetime.now().year`, ATTENTION : tests ne dépendent pas de l'année pour `numero_suivant` au-delà du suffixe `0042`).
- [ ] **Step 4: Lancer → succès** (5 tests).
- [ ] **Step 5: Commit** `git commit -m "feat(operator): modele devis + calculs totaux multi-TVA (purs, testes)"`

---

### Task 15: `devis.from_transcript` (extraction LLM)

**Files:**
- Modify: `jarvis_actions/operator/devis.py` (`from_transcript`), `jarvis_actions/operator/prompts.py` (`extraction_devis`)
- Test: ajout `tests/test_operator_devis.py`

**Interfaces:**
- Produces: `devis.from_transcript(transcript, demander_json, config) -> dict` (LLM → JSON lignes → `construire`). Défensif (json bruité → devis vide avec message).

- [ ] **Step 1: Test (échoue)** — `demander_json` mické renvoyant `{"client": {...}, "lignes": [...]}` → vérifier devis construit + totaux. Cas json invalide → `{"lignes": [], ...}` sans exception.
- [ ] **Step 2-4:** échec → implémenter → succès.
- [ ] **Step 5: Commit** `git commit -m "feat(operator): extraction devis depuis transcript (LLM, defensif)"`

---

### Task 16: `operator/devis_pdf.py` — rendu PDF (fpdf2 optionnel)

**Files:**
- Create: `jarvis_actions/operator/devis_pdf.py`
- Modify: `requirements-windows.txt` (ajouter `fpdf2>=2.7`), `Jarvis.spec`/`JarvisWeb.spec` (hiddenimport `fpdf` si nécessaire)
- Test: `tests/test_operator_devis.py` (ajout)

**Interfaces:**
- Produces: `devis_pdf.disponible() -> bool`, `devis_pdf.rendre(devis, dossier=None) -> str|None` (chemin du PDF ou `None` si fpdf2 absent).

- [ ] **Step 1: Test (échoue)** — si `disponible()` : `rendre(devis)` crée un fichier `.pdf` non vide (dans `tmp_path`) ; si indisponible (monkeypatch `_FPDF=None`) → `rendre` renvoie `None` sans exception. Skip conditionnel si fpdf2 non installé (`pytest.importorskip` côté test « génère vraiment »).

```python
def test_rendre_degrade_sans_fpdf(d_pdf, monkeypatch):
    monkeypatch.setattr(d_pdf, "_disponible_cache", False, raising=False)
    monkeypatch.setattr(d_pdf, "_charger_fpdf", lambda: None)
    assert d_pdf.rendre({"numero": "DEV-1", "lignes": [], "totaux": {}}, dossier=None) is None
```

- [ ] **Step 2-4:** échec → implémenter (`_charger_fpdf` lazy, table lignes, totaux HT/TVA/TTC, en-tête société, mentions) → succès.
- [ ] **Step 5:** `requirements-windows.txt` : ajouter sous la section connecteurs optionnels :

```
fpdf2>=2.7           # generation PDF des devis (Operator ; optionnel)
```

- [ ] **Step 6: Commit** `git commit -m "feat(operator): rendu PDF des devis (fpdf2 optionnel, degradation propre)"`

---

### Task 17: Intent `devis_new` + envoi Gmail après approbation + panneau Devis

**Files:**
- Modify: `jarvis_actions/operator/__init__.py` (`_executer_intent` cas `devis_new` : construit le devis (depuis transcript réunion courant si dispo, sinon dialogue minimal) → `devis_pdf.rendre` → `approvals.ajouter({"type":"send_devis", "payload": {client_email, pdf_path, numero}})` ; `_executeurs_approbation["send_devis"]` = envoi Gmail avec PJ ; `confirmer_depuis_dashboard(aid)` exposé pour le handler dashboard ; `incrementer_compteur_devis` à l'envoi)
- Modify: `jarvis_core/jarvis_dashboard_api.py` (`_h_operator_confirm` appelle `operator.confirmer_depuis_dashboard`)
- Modify: `frontend/src/dashboard/sections_operator.ts` (panneau Devis : file + lien aperçu PDF + Envoyer/Rejeter)
- Test: `tests/test_operator_devis.py` (envoi : exécuteur `send_devis` appelle un faux `messages().send`, incrémente le compteur, journalise)

**Interfaces:**
- Consumes: `devis`, `devis_pdf`, `approvals`, `gmail_ops` (envoi PJ), `config.incrementer_compteur_devis`.
- Produces: `operator.confirmer_depuis_dashboard(aid) -> tuple[str, bool]`, helper `gmail_ops.envoyer_avec_pj(service, to, sujet, corps, pdf_path)`.

- [ ] **Step 1: Test envoi devis (échoue)** — approbation `send_devis` → `confirmer` → faux service `messages().send` appelé avec une PJ encodée ; compteur incrémenté ; `report` journalise « devis_envoye ». **Step 2** échec → **Step 3** implémenter → **Step 4** succès.
- [ ] **Step 5:** Build frontend OK. **Step 6: Commit** `git commit -m "feat(operator): devis -> PDF -> approbation -> envoi Gmail + panneau devis"`

---

# PHASE 6 — Recherche internet + outils agent Gemini + polish

### Task 18: `operator/research.py` — recherche + synthèse

**Files:**
- Create: `jarvis_actions/operator/research.py`
- Test: `tests/test_operator_research.py`

**Interfaces:**
- Produces:
  - `research.shaper_resultats(brut_serp) -> list[dict]` (PUR : normalise une réponse SerpAPI → `[{titre, lien, extrait}]`)
  - `research.rechercher(query, demander_ia, http_get=None) -> dict` (`{resume, sources}` ; SerpAPI si `SERPAPI_API_KEY`, sinon repli `browser.py` ; synthèse LLM ; réseau injecté pour tests)

- [ ] **Step 1: Tests purs (échouent)** — `shaper_resultats` (SerpAPI `organic_results` → liste normalisée, tronque extraits) ; `rechercher` avec `http_get` mické (renvoie un faux JSON SerpAPI) + `demander_ia` mické → `{resume, sources}` peuplé, aucun réseau réel.
- [ ] **Step 2-4:** échec → implémenter → succès.
- [ ] **Step 5: Commit** `git commit -m "feat(operator): recherche internet + synthese (shaping pur teste)"`

---

### Task 19: Intent `research` + panneau Recherche + outils Gemini

**Files:**
- Modify: `jarvis_actions/operator/__init__.py` (`_executer_intent` cas `research` → `research.rechercher` → `show_content` (via `_CTX`) + résumé vocal ; `tools()` renvoie les FunctionDeclarations Gemini : `operator_triage_mail`, `operator_creer_rdv`, `operator_recherche`, `operator_faire_devis` ; `dispatch(name,args)` route vers les fonctions internes)
- Modify: `jarvis_core/main2.py` (`_agent_dispatch` : si `name.startswith("operator_")` → `await jarvis_operator.dispatch(name, args)` ; `run_agent(..., extra_tools=(jarvis_operator.tools() if jarvis_operator else None))`)
- Modify: `frontend/src/dashboard/sections_operator.ts` (panneau Recherche : champ + résultats)
- Modify: `jarvis_core/jarvis_dashboard_api.py` (`dash_operator_research`)
- Test: `tests/test_operator_research.py` (intent + `tools()` non vide + `dispatch` route)

- [ ] **Step 1: Test (échoue)** `tools()` renvoie ≥1 déclaration ; `dispatch("operator_recherche", {...})` appelle `rechercher`. **Step 2** échec → **Step 3** implémenter → **Step 4** succès.
- [ ] **Step 5:** Build frontend OK ; smoke agent (`run_agent` accepte `extra_tools`). **Step 6: Commit** `git commit -m "feat(operator): recherche vocale + outils agent Gemini + panneau recherche"`

---

### Task 20: Documentation + revue finale

**Files:**
- Modify: `CLAUDE.md` (section Operator : modules, flux, scope gmail.modify, dép fpdf2, fichiers gitignorés `jarvis_operator*.json`), `README.md` / `README.en.md` (capacités Operator), `examples/` (vérifier `jarvis_operator_example.json`).

- [ ] **Step 1:** Documenter dans `CLAUDE.md` : nouveau package `jarvis_actions/operator/`, contrat, scheduler, scope Gmail modifié, dép `fpdf2`, fichiers de données gitignorés, onglet dashboard.
- [ ] **Step 2:** README FR + EN (garder synchronisés) : pitch « Operator » + comment activer (config société, ré-consentement Google).
- [ ] **Step 3: Suite complète + build.**

Run: `python -m pytest -q && cd frontend && npx vite build`
Expected: tous tests PASS, build OK.

- [ ] **Step 4:** Revue `code-reviewer` + `security-reviewer` (pas de secret en dur, aucun envoi sans validation, inputs validés).
- [ ] **Step 5: Commit** `git commit -m "docs(operator): documentation CLAUDE.md + README + revue finale"`

---

## Self-Review (couverture spec)

- **Tri email + rapport** → Tasks 7-9 (scope, helpers, scheduler+brouillons+report). ✅
- **RDV / agenda** → Tasks 10-11. ✅
- **Écoute conversation (live + import)** → Tasks 12-13. ✅
- **Devis polyvalent + PDF + validation oui/non + envoi** → Tasks 3 (approbation), 14-17. ✅
- **Recherche internet** → Tasks 18-19. ✅
- **3 surfaces (voix/agent/dashboard) + scheduler** → Tasks 4-6 (façade/wiring/dashboard), 19 (agent). ✅
- **Config société/TVA/compteur + gitignore + example** → Task 1. ✅
- **Vie privée réunion, aucun envoi sans oui, dégradation** → Global Constraints + Tasks 3,13,16. ✅
- **Tests ≥80% modules purs** → chaque module pur a son fichier de test. ✅
- **Docs** → Task 20. ✅

Placeholders : aucun « TBD/TODO » ; le code des fonctions PURES (config, report, approvals, router, devis) est complet ; les tâches d'intégration/UI donnent fichiers + snippets clés + vérif. Cohérence des types : `(str|None, bool)` partout pour les exécuteurs ; `approvals.confirmer(id, executeurs)` ; `report.journaliser(dict)`.
