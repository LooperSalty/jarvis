# Spec — Sous-système « Operator IA »

Date : 2026-06-28
Statut : approuvé (design), prêt pour plan d'implémentation
Auteur : Jarvis / ANAKIN

## 1. Objectif

Ajouter à Jarvis un assistant opérationnel (« Operator ») qui :

1. **Trie la boîte mail** automatiquement (classe / étiquette / archive) et **rend compte** de ce qu'il a fait.
2. **Gère les RDV et l'emploi du temps** (lecture riche, création/modification/suppression d'événements, créneaux libres).
3. **Écoute les conversations** — mode réunion live à la demande **et** import d'un fichier audio — pour en tirer un résumé et les éléments d'un devis.
4. **Génère des devis** (modèle polyvalent prestation/matériau/produit, PDF) et les **envoie par email après validation « oui/non »** de l'utilisateur.
5. **Fait des recherches sur internet** et restitue une synthèse.

## 2. Décisions produit (validées)

| Sujet | Décision |
|---|---|
| Type de devis | **Polyvalent** : un même devis peut mêler prestations, matériaux et produits (libellé, type, quantité, unité, PU HT, taux TVA). |
| Production / envoi du devis | **PDF** propre (numéro, client, lignes, totaux HT/TVA multi-taux/TTC) **envoyé par Gmail en pièce jointe** après validation. Dégradation : Google Doc si la lib PDF est absente. |
| Écoute des conversations | **À la demande (mode réunion live)** + **import d'un fichier audio**. Pas d'écoute ambiante permanente. |
| Autonomie email | **Tri auto + réponses validées** : classe/étiquette/archive seul puis rapporte ; les **réponses sont des brouillons** soumis au « oui » avant envoi. |
| Canal d'approbation | Diffusé à **tous les clients** (voix + dashboard + mobile) via le broadcast WS existant. |
| Cerveau | Réutilise la chaîne `demander_ia` existante (Gemini primaire, Ollama repli) ; extractions structurées en JSON (pattern `memory_proactive`). |

## 3. Approche architecturale

Package first-class `jarvis_actions/operator/` (petits modules, haute cohésion), branché aux **trois surfaces existantes** + un **planificateur de fond** :

- **Voix** : `async_executer(cmd)` plugué dans `traiter_reponse_ia` (contrat `(str|None, bool)`).
- **Agent Gemini** : `tools()` (FunctionDeclarations) + `dispatch(name, args)` injectés comme les outils MCP (`extra_tools`).
- **Dashboard** : handlers `dash_operator_*` routés depuis `jarvis_dashboard_api.py` + nouvel onglet principal.
- **Fond** : `demarrer_planificateur()` lancé en `asyncio.create_task` dans `start_ia` (pattern `routines`).

Rejeté : un seul gros `operator.py` (viole « petits fichiers ») ; tout en skills `jarvis_skills/` (trop léger pour scheduler + dashboard + Google).

## 4. Modules du package

```
jarvis_actions/operator/
├── __init__.py        # façade : init(ctx), async_executer, tools()/dispatch(), demarrer_planificateur()
├── config.py          # jarvis_operator.json (gitignoré) + validation liste blanche
├── gmail_ops.py       # threads, classif LLM, étiquette/archive, brouillons réponse
├── calendar_ops.py    # CRUD événements, créneaux libres, parsing RDV NL→payload
├── meeting.py         # mode réunion live (transcription continue) + import fichier audio
├── devis.py           # modèle polyvalent + calculs purs + numérotation + from_transcript()
├── devis_pdf.py       # rendu PDF (fpdf2) ; dégrade en Google Doc
├── research.py        # SerpAPI + browser.py → synthèse structurée
├── approvals.py       # file d'approbation persistée + diffusion + confirmer/rejeter
├── report.py          # journal d'activité + restitution « ce que j'ai fait »
└── prompts.py         # gabarits LLM isolés
```

### Responsabilités et interfaces

- **`config.py`** : `charger() -> dict`, `sauvegarder(updates) -> dict` (écriture atomique `.tmp`+`os.replace`), liste blanche de clés (société, TVA, compteur devis, règles de tri, autonomie, plages horaires). Modèle versionné `examples/jarvis_operator_example.json`. Persistance via le pattern `_dossier_donnees()` (à côté de l'exe en frozen).
- **`gmail_ops.py`** : `lister_threads_non_lus(service, n)`, `classer(thread, demander_json) -> dict {categorie, priorite, action, besoin_reponse}`, `appliquer_label(service, id, label)`, `archiver(service, id)`, `creer_brouillon(service, thread, corps)`. Crée les labels manquants. Détection pure + appels Gmail isolés.
- **`calendar_ops.py`** : `lister(service, debut, fin)`, `creer(service, payload)`, `modifier`, `supprimer`, `creneaux_libres(service, contraintes)`, `parser_rdv(texte, demander_json) -> payload`.
- **`meeting.py`** : `demarrer(broadcast)` (boucle de transcription continue **sans** wake-word, diffuse les chunks), `arreter() -> transcript`, `transcrire_fichier(path) -> transcript`, `resumer(transcript, demander_ia) -> str`. Réutilise `voice_stt`/faster-whisper.
- **`devis.py`** : structures immuables. `ligne(...)`, `calculer_totaux(lignes) -> {ht, tva_par_taux, tva_total, ttc}` (PUR, multi-taux), `numero_suivant(config) -> str`, `from_transcript(transcript, demander_json) -> devis`.
- **`devis_pdf.py`** : `rendre(devis, societe) -> chemin_pdf` (fpdf2) ; si fpdf2 absent → `None` + signal de repli Google Doc.
- **`research.py`** : `rechercher(query) -> {resume, sources}` (SerpAPI si clé, sinon browser.py), synthèse LLM.
- **`approvals.py`** : `ajouter(action) -> id`, `lister() -> list`, `confirmer(id) -> resultat`, `rejeter(id)`, persistance + broadcast `operator_pending`. Types : `send_devis`, `send_email_reply`.
- **`report.py`** : `journaliser(evenement)`, `resume() -> str`, broadcast `operator_activity`.

## 5. Intégration `main2.py`

1. `operator.init({ get_gmail_service, get_calendar_service, get_docs_service, demander_ia, demander_json, parler, broadcast_ws, memoire_ops, user_name })` après définition des getters Google.
2. Bloc `await operator.async_executer(cmd)` dans `traiter_reponse_ia`, **après le bloc `browser`** (pour que « cherche X sur google » reste au navigateur), avec regexes étroites :
   - tri : `trie?s? (mes )?mails?`, `t(u t')?occupe.*mails?`
   - réunion : `écoute (la )?réunion|conversation`, `arrête d'écouter|stop réunion`
   - devis : `fais?\s+(un|le)\s+devis`, `prépare un devis`
   - RDV : `prends? (un )?rdv|rendez-vous|ajoute.*agenda`
   - recherche : `recherche (approfondie|sur internet)`, `fais des recherches sur`
   - approbation : `^(oui|valide|envoie|d'accord|non|annule|refuse)` **uniquement si `approvals.lister()` non vide** (sinon `(None, False)`).
3. Outils Gemini : `run_agent(..., extra_tools=operator.tools())` + branche `operator.dispatch` dans `_agent_dispatch`.
4. `asyncio.create_task(operator.demarrer_planificateur(...))` dans `start_ia`.
5. **Scope Gmail** : ajouter `https://www.googleapis.com/auth/gmail.modify` à `SCOPES` (étiqueter/archiver l'exige). Conséquence : **une ré-autorisation Google** au prochain démarrage (token.pickle régénéré).

## 6. Dashboard (frontend)

Nouvel onglet principal « Operator » : `frontend/src/dashboard/sections_operator.ts`, ajouté à `SECTIONS` + `MAIN_SECTION_IDS`. Sous-panneaux :

- **Boîte mail** : rapport d'activité + liste des brouillons en attente → Valider / Modifier / Rejeter.
- **Agenda/RDV** : prochains événements, création rapide, créneaux libres.
- **Réunion** : Démarrer/Arrêter l'écoute, transcript live, « Générer compte-rendu », « Générer devis », zone d'import audio.
- **Devis** : file d'attente + aperçu PDF + Envoyer / Modifier / Annuler + historique.
- **Recherche** : requête → synthèse + sources.
- **Réglages Operator** : infos société (devis), règles de tri, plages horaires, niveau d'autonomie, compteur de devis.

Contrat WS `dash_operator_*` (routé depuis `jarvis_dashboard_api.py`, callables injectés via `init_api`) : `dash_operator_init` / `dash_operator_state`, `dash_operator_activity`, `dash_operator_pending` (+ `dash_operator_confirm` / `dash_operator_reject`), `dash_operator_meeting_*` (start/stop/transcript/import), `dash_operator_research`, `dash_operator_settings_get` / `dash_operator_settings_set`.

## 7. Flux de données

1. **Tri email (fond, toutes N min)** : `lister_threads_non_lus` → `classer` (LLM JSON) → étiquette/archive selon règles → si réponse requise : `creer_brouillon` + `approvals.ajouter(email_reply)` → `report.journaliser`. Restitution : « J'ai traité 12 mails : 3 Factures, 2 archivés, 4 à valider. »
2. **RDV** : « prends rdv mardi 14h » → `parser_rdv` → `creneaux_libres` → `creer` → rapport.
3. **Réunion → devis** : « écoute la réunion » → `meeting.demarrer` (transcript diffusé) → « stop » → `resumer` → `devis.from_transcript` → `devis_pdf.rendre` (aperçu) → `approvals.ajouter(send_devis)` → « oui » → envoi Gmail (PDF joint) → rapport.
4. **Recherche** : « fais une recherche sur X » → `research.rechercher` → carte `show_content` + résumé vocal.

## 8. Approbation

File centrale `approvals`. Si ≥1 en attente et « oui/valide/envoie » (ou clic) → confirme (la plus récente ou par id). « non/annule » → rejette. Broadcast à tous les clients. L'`async_executer` n'intercepte « oui/non » **que** si une approbation existe (sinon ne hijacke pas la conversation normale).

## 9. Config & secrets

- `jarvis_operator.json` (gitignoré) + `examples/jarvis_operator_example.json` : société, taux TVA, numérotation devis, règles de tri, flags autonomie, plages horaires.
- `SCOPES` += `gmail.modify`.
- Réutilise `SERPAPI_API_KEY`, `GEMINI_API_KEY` existants. Clé éventuelle `JARVIS_OPERATOR_TRIAGE_MIN` (intervalle), ajoutée à `CLES_GEREES` si surfacée.
- Nouvelle dép `fpdf2` (optionnelle) → `requirements-windows.txt`. faster-whisper déjà optionnel.
- Spec PyInstaller : ajouter `fpdf` aux hiddenimports si nécessaire ; ne pas embarquer `jarvis_operator.json` (secret-like).

## 10. Vie privée & robustesse

- Mode réunion : start/stop explicite, état « écoute » visible (orbe + dashboard), transcript **local uniquement** (gitignoré), jamais auto-envoyé.
- Tous les appels Google/LLM enveloppés try/except, ne crashent jamais la boucle.
- **Aucun email/devis envoyé sans « oui » explicite.**
- Chaque dép externe optionnelle (fpdf2, faster-whisper, creds Google, SerpAPI) → dégradation propre avec message.

## 11. Tests (pytest, viser 80%)

Fonctions pures testées sans réseau (LLM/Google mockés) :
- `devis.calculer_totaux` (multi-TVA, arrondis), `devis.numero_suivant`.
- Matching des règles de tri email.
- CRUD `approvals` + sélection « plus récente ».
- Validation `config` (liste blanche, valeurs invalides rejetées).
- Parsing JSON RDV/devis (LLM mocké, tolérant aux entrées bruitées).
- Routage `async_executer` (regexes, garde « oui/non » conditionnelle).
- Shaping résultats `research`.

## 12. Séquencement (→ plan d'implémentation)

1. **Squelette** : package + `config` + façade `init` + coquille onglet dashboard + `report`/activity feed + tests.
2. **Email** : `gmail_ops` tri (+ scope `gmail.modify`) + scheduler + brouillons + `approvals`.
3. **Agenda** : `calendar_ops` RDV/agenda.
4. **Réunion** : `meeting` (live + import) + résumé.
5. **Devis** : `devis` (modèle + PDF + from_transcript) + envoi + approbation.
6. **Recherche + agent** : `research` + outils Gemini + polish + maj `CLAUDE.md`/README.

## 13. Critères d'acceptation

- Onglet « Operator » fonctionnel dans le dashboard.
- Commande vocale « trie mes mails » → tri + rapport (« voici ce que j'ai fait »).
- « prends rdv … » crée un événement Calendar.
- « écoute la réunion » → transcript live → « stop » → résumé ; import audio fonctionne.
- « fais un devis » (ou depuis une réunion) → PDF aperçu → « oui » → email envoyé au client.
- « fais une recherche sur X » → synthèse + sources.
- Aucun envoi sortant sans validation explicite.
- Suite pytest verte, couverture ≥ 80 % sur les modules purs.
- `CLAUDE.md` / README mis à jour.
