# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Structure

```
jarvis/
├── Jarvis.exe / JarvisWeb.exe / ModelAdvisor.exe  ← double-cliquables (gitignored ; Jarvis/Web = onedir : exe + dossier _internal/_internal_web a cote)
├── build_all.bat                                  ← rebuild les 3 .exe + copie a la racine
├── Dockerfile / docker-compose.yml / .dockerignore ← image serveur headless (Linux)
├── requirements-docker.txt                        ← deps minimales Linux (PAS le freeze Windows)
├── jarvis_core/                                   ← TOUS les modules Python (lancer via `python jarvis_core/main2.py`). Dossier source PLAT ajouté à sys.path — PAS un package : imports à plat (`from jarvis_config import …`).
│   ├── main2.py                                   ← gros entry point (backend, WS, voix, IA)
│   ├── jarvis_desktop.py / jarvis_web.py          ← entries des 2 modes Jarvis
│   ├── jarvis_config.py                           ← USER_NAME + chargement .env précoce
│   ├── jarvis_brain_local.py                      ← cerveau local Ollama (extrait de main2.py)
│   ├── jarvis_profile.py                          ← profil utilisateur enrichi (famille, adresse, habitudes)
│   ├── jarvis_ui_config.py                        ← config UI persistante (thème, couleur de l'orbe, dossier Cowork)
│   ├── jarvis_security.py / jarvis_secrets.py     ← validation entrees + gestion clés/.env
│   ├── jarvis_version.py                          ← version + check_update (release GitHub par tag)
│   ├── jarvis_dashboard_api.py                    ← routeur WS des messages dash_* (app de configuration)
│   └── jarvis_home_config.py + _example.py        ← config domotique perso (gitignoré) + modèle versionné
├── Jarvis.spec / JarvisWeb.spec                   ← specs PyInstaller (entry = jarvis_core/…, pathex inclut jarvis_core/)
├── jarvis_actions/                                ← package modules d'actions importes par main2
│   ├── pc_actions.py / system_actions.py / dev_actions.py
│   ├── claude_bridge.py / obsidian_memory.py
│   ├── spotify.py / messaging_bridge.py / openclaw.py  ← connecteurs (PR #8/#11)
│   ├── voice_stt.py / wake_word.py / barge_in.py  ← pipeline voix avancé
│   ├── routines.py / triggers.py                  ← automatisations (cron + déclencheurs)
│   ├── memory_rag.py / memory_proactive.py / history_summary.py  ← mémoire RAG + résumé
│   ├── memory_sync.py                             ← export mémoire → Obsidian / Google Drive / Notion
│   ├── display_actions.py                         ← fenetres d'affichage ("montre-moi X"), cross-platform
│   ├── mcp_client.py                              ← client MCP stdio (connecteurs externes)
│   ├── skills_loader.py                           ← auto-decouverte des skills jarvis_skills/
│   └── model_advisor_service.py                   ← specs PC + reco de modeles (vendorise model_advisor)
├── jarvis_skills/                                 ← skills utilisateur auto-charges (template dans README.md)
├── installer/JarvisSetup.iss                      ← installateur Windows (Inno Setup, FR/EN, option Ollama+modele)
├── tests/                                         ← suite pytest (158 tests, 13 fichiers)
├── scripts/                                       ← entries secondaires
│   ├── jarvis_tray.py / jarvis_notify.py / Lancer_Jarvis.bat
│   ├── jcode.cmd                                  ← ouvre une session Claude Code interactive (tous les outils) ; a copier sur le PATH (le nom `jarvis` est pris par le package OpenJarvis)
│   ├── build_installer.bat                        ← compile JarvisSetup-<version>.exe (Inno Setup requis)
├── .github/workflows/                             ← ci.yml (python+frontend+secrets) + release.yml (tag → .exe/installateur/macOS)
├── README.md / README.en.md                       ← doc utilisateur FR / EN (garder les deux synchronisees)
├── docs/                                          ← placeholders config (VOS_API.txt, ...)
├── examples/                                      ← modèles *_example.json à copier (templates, jamais chargés par le code)
├── frontend/                                      ← UI Three.js + Vite (index.html = orbe, dashboard.html = config)
├── mobile/                                        ← interface mobile statique
└── model_advisor/                                 ← sous-projet recommandeur LLM
```

## Démarrage

```bash
# Solution 1 : double-clique sur Jarvis.exe / JarvisWeb.exe / ModelAdvisor.exe (a la racine)
# Solution 2 : en dev — les modules Python sont dans jarvis_core/ (lancer DEPUIS la racine)
python jarvis_core/main2.py           # backend + Vite + ouvre navigateur
python jarvis_core/jarvis_desktop.py  # mode arriere-plan (system tray + mini orbe)
python jarvis_core/jarvis_web.py      # backend + ouvre navigateur (sans Vite, sert dist/)
python scripts/jarvis_tray.py         # alternative system tray (lance main2 en sous-process)

# Build des 3 .exe + copie a la racine (necessite frontend/dist deja build)
build_all.bat

# Installateur Windows JarvisSetup-<version>.exe (apres build_all.bat ;
# Inno Setup 6 requis : winget install JRSoftware.InnoSetup)
scripts\build_installer.bat

# Builds individuels
python -m PyInstaller Jarvis.spec --clean --noconfirm           # onedir -> dist/Jarvis/ (Jarvis.exe + _internal/)
python -m PyInstaller JarvisWeb.spec --clean --noconfirm        # onedir -> dist/JarvisWeb/ (JarvisWeb.exe + _internal_web/)
cd model_advisor && python -m PyInstaller --onefile --windowed --name ModelAdvisor --clean --noconfirm model_advisor.py

# Frontend seul (dev avec HMR)
cd frontend && npm run dev          # http://localhost:5173

# Dépendances
python -m pip install -r requirements-windows.txt  # set runtime épuré Windows (build .exe + dev)
python -m pip install -r requirements-voice.txt    # pipeline voix avancé (STT/wake word/barge-in)
python -m pip install -r requirements-macos.txt    # extras macOS
cd frontend && npm install
# NB : requirements.txt est un freeze complet de la machine dev (aider, kimi...)
# dont les pins sont en conflit entre eux : NE PAS l'utiliser sur un env vierge
# (ResolutionImpossible). requirements-windows.txt est la liste curatée.

# Mode 100% local (force Ollama, ignore les clés cloud)
FORCE_OLLAMA=1 python jarvis_core/main2.py
ollama serve && ollama pull llama3.2:3b

# Docker (mode serveur headless — pas de micro/audio/GUI, STT/TTS côté navigateur)
docker compose up -d --build                    # backend seul (cerveau cloud)
docker compose --profile local up -d --build    # + Ollama embarqué (100% local)
# Image basée sur requirements-docker.txt (set minimal Linux), PAS requirements.txt.
# Ports publiés : 5173 (orbe+dashboard), 8080 (mobile), 8765 (WebSocket).
```

Le `.bat` `DÉMARRER_JARVIS.bat` (non versionné) contient un chemin Python codé en dur et n'est pas portable — utilise `python jarvis_core/main2.py` directement (ou `scripts/Lancer_Jarvis.bat` qui est plus simple).

Tests : suite **pytest** (158 tests dans `tests/`, config `pytest.ini` → `testpaths=tests`). Lancer avec `python -m pytest`. CI GitHub Actions (`.github/workflows/ci.yml`) exécute 3 jobs sur chaque PR : `python` (pytest), `frontend` (build Vite), `secrets` (scan de secrets). Pas de linter configuré. Étape de build frontend : `cd frontend && npm run build` (Vite production).

Release (`.github/workflows/release.yml`, déclenchée par tag `vX.Y.Z`) : build frontend + `Jarvis.exe`/`JarvisWeb.exe`/`ModelAdvisor.exe` + **installateur `JarvisSetup-x.y.z.exe`** (Inno Setup, préinstallé sur les runners `windows-latest`, fallback chocolatey) + binaire macOS best-effort. L'installateur est un livrable BLOQUANT (la release échoue s'il manque). Le `.iss` lit la version dans `jarvis_version.py` si `/DAppVersion` n'est pas passé.

### Envoyer une commande depuis l'extérieur

`jarvis_notify.py` est un client WebSocket CLI minimal qui se connecte à `ws://localhost:8765` :
```bash
python jarvis_notify.py "message a vocaliser"          # type=tell par defaut
python jarvis_notify.py --type cmd "ouvre chrome"      # comme une commande mobile
```
Pratique depuis hooks, scripts, ou autres process pour piloter Jarvis sans passer par la voix.

## Architecture

**`main2.py` (~4300 lignes) est le point d'entrée monolithique.** Il orchestre :

1. **WebSocket server** sur `ws://0.0.0.0:8765` (`ws_handler`) — multiplexe les clients web (frontend Vite), mobile ET le dashboard de configuration. Messages entrants : `mobile_command`, `text_command`, `external_say`, `stop_audio`, `set_mute`, `screen_frame`, `request_history`, `request_conversation(s)`, et tous les `dash_*` (délégués à `jarvis_dashboard_api.traiter_message_dashboard` en premier). Messages sortants : `set_state`, `set_volume`, `chat_message`, `request_screen_capture`, `jarvis_response`, `history`, et les réponses `dash_*`.
2. **Serveur HTTP** sur `:8080` qui sert `mobile/` (interface mobile statique).
3. **Auto-launch Vite** : `subprocess.Popen(["npm", "run", "dev"], cwd=frontend_dir)` puis `webbrowser.open("http://localhost:5173")`.
4. **Boucle voix** (`start_ia` + `ecouter`) : reconnaissance vocale via `speech_recognition`, mot-clé d'activation `"jarvis"`, détection de claps en parallèle.
5. **TTS** (`parler`) : `edge_tts` (voix `fr-FR-HenriNeural`) → mp3 → `pygame.mixer.music`.

### Cerveau IA — chaîne de fallback

`demander_ia(texte)` (ligne ~1500) suit cet ordre :

```
FORCE_OLLAMA → Ollama direct (court-circuit total)
sinon : Gemini (5 modèles tentés) → SerpAPI → Groq → Grok → Ollama
```

`detecter_cerveau()` peut router vers Grok en premier selon la requête. **`FORCE_OLLAMA=1` est activé automatiquement quand `GEMINI_API_KEY` est manquante ou égale à `VOTRE_API`** (voir `_cle_valide()` ligne 50). Le client Gemini est `None` dans ce cas pour éviter les appels réseau inutiles.

`demander_ollama` découvre les modèles installés via `GET /api/tags` au premier appel et ré-ordonne `OLLAMA_MODELS` selon ce qui est dispo.

### État partagé global

Variables globales modifiées de partout — fais attention en éditant :
- `historique` : liste de `types.Content` Gemini, source de vérité de la conversation
- `CONNECTED_CLIENTS` : set de WebSockets actifs
- `_skip_pc_audio` : `True` quand commande vient du mobile (le tél fait son propre TTS, le PC n'émet pas le son)
- `STOP_PARLER`, `is_speaking`, `is_thinking`, `speak_volume`, `jarvis_actif`, `MODE_IRON_MAN`
- `dossier_courant` : contexte navigation fichiers

### Intégrations externes

- **Home Assistant** : `HA_URL` + `HA_TOKEN`, helpers `ha_lumiere`/`ha_thermostat`/`ha_scene` qui POST sur `/api/services/...`
- **Google APIs** (Gmail/Docs/Drive/Calendar/Sheets) : OAuth via `credentials.json` + token sérialisé local (`get_google_creds`)
- **Vision écran** : le frontend partage l'écran via `getDisplayMedia` (`screen_capture.ts`), le backend demande une frame via WebSocket `request_screen_capture`, attend la réponse via `PENDING_SCREEN_CAPTURES[req_id]`, puis l'envoie à Gemini multimodal
- **Météo** : géocodage Nominatim → Open-Meteo (pas de clé)
- **Foot** : Gemini en mode "fait sportif" (pas d'API dédiée)

### Mémoire

Deux mémoires distinctes :
- `jarvis_memoire.json` : persistant, clé/valeur datés (`ajouter_memoire`, `supprimer_memoire`, intégré dans `construire_system_prompt`)
- `historique` : in-memory uniquement, conversation complète, jamais sauvegardée

`jarvis_agent.py` est un **scaffold alternatif inutilisé** (extrait de `main2.py` en mini-classe `JarvisAgent`). Ne pas confondre — toute la logique active est dans `main2.py`.

### App de configuration (dashboard)

Page Vite séparée `frontend/dashboard.html` (sources `frontend/src/dashboard/`), accessible sur `http://localhost:5173/dashboard.html`, via le lien ⚙ de l'orbe, ou les entrées "Configuration" des menus tray. **Navigation à deux niveaux** (`MAIN_SECTION_IDS` dans `sections.ts`, routage dans `dashboard/main.ts`) : 4 onglets PRINCIPAUX dans la sidebar — **Chat / Cowork / Code / Automatisation** — puis un bouton **Paramètres** qui ouvre une page avec sous-onglets pour le reste : Vue d'ensemble (clés API présentes/absentes — jamais les valeurs —, intégrations, nom utilisateur), Profil (famille/adresse/habitudes/routines → injecté dans le system prompt par `jarvis_profile.contexte_profil()`), Mémoire (graphe d3-force via `graph.ts` + CRUD + **synchronisation externe**), Connecteurs (serveurs MCP + skills Jarvis), **Skills** (skills Claude Code installables en un clic), Modèle IA (specs PC + reco Ollama), Personnalisation (thème + apparence de l'orbe). `DEFAULT_SECTION_ID = "chat"`.

- **Onglet Code** (`frontend/src/dashboard/sections_code.ts` + `jarvis_actions/free_code.py`) : onglet PRINCIPAL qui embarque l'**Admin UI de free-claude-code** (proxy `fcc-server`, providers/modèles) dans une **iframe** (`http://127.0.0.1:8082/admin` — aucun en-tête anti-iframe). Permet de configurer le modèle de code local/gratuit (Qwen/DeepSeek) sans quitter Jarvis. Handlers `dash_fcc_status` (installé/en marche/url) et `dash_fcc_start` (démarre `fcc-server` détaché). Si le proxy est éteint → bouton « Démarrer le proxy » + re-poll. Lié à la commande terminal `jarvis` (cf. mémoire `jarvis_commande_free_claude_code`).
- **Skills Claude Code** (sous-onglet **Skills** de Paramètres, `frontend/src/dashboard/sections_cc_skills.ts` + `jarvis_actions/cc_skills.py`) : catalogue (liste blanche `CATALOGUE`) de marketplaces de skills Claude Code réputées (anthropics/skills, mattpocock/skills…) avec ajout en 1 clic via `claude plugin marketplace add <repo>`. Plus Claude Code a de skills, plus le **Cowork** et la commande **jcode** sont puissants. Handlers `dash_cc_skills` (catalogue + marketplaces déjà ajoutées, parsées depuis `claude plugin marketplace list`) / `dash_cc_skill_add {repo}` (refuse tout repo hors liste blanche). `subprocess` en `encoding="utf-8"` (la sortie `claude` contient des caractères non-cp1252). `_parser_marketplaces` est pur et testé.

- **Personnalisation / Cowork** (`sections_personnalisation.ts` / `sections_cowork.ts`) : persistés dans `jarvis_ui_config.json` (gitignoré, validé par `jarvis_ui_config.py` : liste blanche de thèmes/styles/**formes**, regex couleur, existence du dossier). Le couple thème→accent+fond, style→palette d'orbe, et la résolution de forme sont centralisés dans `frontend/src/ui_theme.ts` (partagé page orbe ↔ dashboard). Le thème change l'accent ET le fond (`--bg-0/1`) pour être visuellement distinct. La **forme de l'orbe** (`orb_shape` : galaxie/œil/anneau, géométries dans `orb.ts`) ET sa couleur sont **diffusées en live** à la page orbe (`dash_ui` via le callable `diffuser_ui` injecté dans `init_api`) : `orb.setPalette` pour la couleur, recréation de l'orbe (`orb.dispose()` + `createOrb`, canvas neuf) pour la forme. Le Cowork lance Claude Code dans le dossier via `claude_bridge.lancer_claude_code(prompt, cwd=...)` (délégation one-shot `claude --print`). Le bouton **« Ouvrir une session de code »** (handler `dash_cowork_session`) ouvre lui une session Claude Code **interactive** dans un nouveau terminal via `claude_bridge.ouvrir_session_terminal(cwd)` (`cmd /k claude` en `CREATE_NEW_CONSOLE` sous Windows ; best-effort ailleurs) — équivalent in-app de la commande `jcode`.
- **Synchronisation de la mémoire** (section Mémoire, `jarvis_actions/memory_sync.py`) : exporte/sauvegarde la mémoire vers **Obsidian** (`ObsidianBridge.save_memory` par souvenir), **Google Drive** (fichier `jarvis_memoire.json` via `get_drive_service` injecté dans `init_api` — peut déclencher l'OAuth), et **Notion** (un bloc puce par souvenir via l'API, clés `NOTION_TOKEN` + `NOTION_PAGE_ID`). Handlers `dash_memory_connectors` (statut) / `dash_memory_sync {target}`, chaque connecteur dégradé proprement si non configuré.

- **Protocole** : tout passe par le WS 8765, messages `dash_*` (contrat complet en tête de `jarvis_dashboard_api.py` et `frontend/src/dashboard/ws.ts`).
- **`jarvis_dashboard_api.py`** : routeur injecté par `init_api(contexte)` depuis main2 (callables mémoire + user_name). Écrit le `.env` ATOMIQUEMENT avec liste blanche de clés (`CLES_GEREES`) ; ne renvoie JAMAIS une valeur de clé au client (booléens uniquement). `restart_required` devient `True` après tout `dash_set_env`.
- **MCP** (`jarvis_actions/mcp_client.py`) : client stdio JSON-RPC sans dépendance, config `jarvis_mcp.json` (gitignoré, modèle `examples/jarvis_mcp_example.json`). Les tools des serveurs `enabled` sont exposés à la boucle agent Gemini au démarrage (`_init_mcp_tools` dans main2, noms `mcp_<serveur>_<tool>`). Les sessions vivent sur l'event loop du serveur WS — toujours awaiter depuis ce loop.
- **Skills** (`jarvis_skills/*.py`) : auto-découverts par `skills_loader`, contrat `SKILL = {...}` + `executer(cmd) -> (str|None, bool)` (ou `async_executer`). Branchés dans `traiter_reponse_ia` AVANT `pc_actions`. En mode .exe, un skill peut être déposé à côté du binaire sans rebuild.
- **Affichage** (`display_actions.py`) : `montrer_contenu(titre, contenu, type)` génère une carte HTML sombre dans `%TEMP%/jarvis_affichage/` et l'ouvre (startfile / `open` / `xdg-open`). Exposé à l'agent Gemini comme tool `show_content` ("montre-moi...").
- **Modèles** (`model_advisor_service.py`) : copie vendorisée de la base de `model_advisor/model_advisor.py` (commentaire "Synchronise depuis..." — mettre à jour les deux), détection specs cross-platform, reco top 8 + flag `installe` via Ollama `/api/tags`.

### Modules d'actions (importés par `main2.py`)

Détection locale par mots-clés AVANT tout appel IA — économise des appels Gemini/Ollama :

- **`pc_actions.py`** : ouvre/ferme apps Windows (`chrome`, `vscode`, `discord`...), navigue sites (`youtube`, `gmail`, `google maps`...), capture d'écran, contrôle souris/clavier via `pyautogui`. Mappings dans `_APP_ALIASES` et `_WEB_SHORTCUTS`. Retourne `(reponse, success)` ou `(None, False)` si non reconnu.
- **`system_actions.py`** : actions système avancées. **Énergie** (`éteins/redémarre/mets en veille/déconnecte le pc`, délai annulable de 30 s : `annule l'extinction`). **Fenêtres** (`réduis tout`, `agrandis/réduis la fenêtre`, `change de fenêtre`, `fenêtre à gauche/droite`). **Bureaux virtuels** (`vue des tâches`, `bureau suivant/précédent`, `nouveau bureau`). **Raccourcis** navigateur/édition (`nouvel onglet`, `ferme/rouvre l'onglet`, `actualise`, `plein écran`=F11, `recherche dans la page`, `zoom avant/arrière/normal`). **Volume** (`au maximum/minimum`, `volume à X%` via pas clavier de 2 %, dep-free). **Panneaux de paramètres Windows** via URI `ms-settings:` sans admin (`ouvre le wifi/bluetooth`, `paramètres son/affichage` — permet de toggler WiFi/BT à la main). **Infos** lecture seule (`batterie`, `processeur`, `mémoire`, `espace disque`, `état du pc`, `adresse ip`, `nom du pc`, `uptime` via `psutil`/`socket`). **Process** (`ferme chrome` → `taskkill`), **presse-papier** (`pyperclip`), **corbeille**. Cœur = `detecter_intention(cmd)` (routeur **pur** texte→intention, table `_REGLES` + capture spéciale pour volume%/process ; entièrement testé) + handlers à dépendances **optionnelles** (`pyautogui`/`psutil`/`pyperclip` → dégradation propre en CI/headless). Branché dans `traiter_reponse_ia` **AVANT `pc_actions`** (sinon « éteins le pc » serait confondu avec l'ouverture d'app). « éteins tout »/« éteins la lumière » ne déclenchent PAS l'arrêt (laissés à la domotique).
- **`dev_actions.py`** : ouvre des projets par nom (scan `~/Downloads`, `~/Documents`, `~/Desktop`, `~/Projects`, `~/Code`, `~/dev` à profondeur ≤ 4, marqueurs `.git`/`package.json`/`pyproject.toml`/`Cargo.toml`/`go.mod`/`pom.xml`), git status/pull/push, timer, presse-papier, terminal.
- **`claude_bridge.py`** : surveille `~/.claude/projects/` (mtime du dernier fichier) et lance `claude` CLI en mode non-interactif (`shutil.which("claude")` puis `subprocess`). Permet à Jarvis de déléguer une tâche de code à Claude Code.
- **`obsidian_memory.py`** : `ObsidianBridge(vault_path)` synchronise mémoire Jarvis ↔ Obsidian. Crée `{vault}/Jarvis/Memoire/*.md` (une note par clé), `{vault}/Jarvis/Conversations/{YYYY-MM-DD}.md` (log quotidien), `{vault}/Jarvis/Notes/`. `_slugify` impose noms de fichiers ASCII safe. Ne déclenche RIEN si le vault n'existe pas (`FileNotFoundError`).
- **`meross.py`** : contrôle des prises Wi-Fi Meross (MSS710 etc.) via le cloud. Pre-requis `MEROSS_EMAIL` + `MEROSS_PASSWORD` dans `.env`. Manager lazy-init (login une seule fois). Détection mots-clés : `allume la lumière` → ON, `éteins la lumière` → OFF, juste `lumière`/`lampe` seul → **TOGGLE** (lit l'état actuel via `is_on()` puis inverse). Async natif (les autres modules sont sync, celui-ci expose `async_executer` et est awaité directement par `traiter_reponse_ia`). Branché AVANT `pc_actions` pour matcher en premier.
- **`browser.py`** : pilote un Chromium via Playwright (`playwright install chromium` requis une fois). Singleton lazy-init avec profil persistant (`%TEMP%/jarvis_browser_profile`) pour rester loggé entre sessions. Commandes : `va sur youtube`/`ouvre amazon` (navigation, dictionnaire `_SITES` de 25 sites courants), `cherche X sur google/youtube/amazon` (search engines), `lis-moi la page` (extract `<main>`/`<article>`/body, tronqué à 1500 chars), `clique sur [texte]` (`get_by_text`), `tape [texte] dans [champ]` (`get_by_label`/`get_by_placeholder`), `screenshot`, `ferme le navigateur`. Async natif comme meross. Branché APRÈS meross mais AVANT pc_actions.
- **`openclaw.py`** : pont vers un agent [OpenClaw](https://docs.openclaw.ai) local (gateway `http://127.0.0.1:18789`). Deux tokens DISTINCTS : `OPENCLAW_TOKEN` (= `gateway.auth.token`, pour `demande à openclaw X` → POST `/v1/chat/completions` synchrone, `model="openclaw"`, `user="conv:jarvis"` = session stable côté OpenClaw) et `OPENCLAW_HOOKS_TOKEN` (= `hooks.token`, pour `envoie à openclaw X` → POST `/hooks/agent` fire-and-forget avec `deliver=true`, et `préviens openclaw que X` → POST `/hooks/wake`). `statut openclaw` → GET `/health` (sans auth). Côté OpenClaw, l'endpoint OpenAI doit être activé (`gateway.http.endpoints.chatCompletions.enabled=true`) et les hooks aussi (`hooks.enabled=true`). Async natif, branché APRÈS spotify, AVANT les skills. Aussi exposé comme tool Gemini `ask_openclaw` (déclaré dans `jarvis_actions/agent.py`).

### Frontend (`frontend/src/`)

- **`main.ts`** : connexion WebSocket avec auto-reconnect, dispatcher vers l'orbe selon les messages. Écoute le bouton mute (envoie `stop_audio`) et le bouton vision (`injectVisionButton`).
- **`orb.ts`** : Three.js, rendu = particules sur courbes Lissajous (28 orbites × 320 points) + sprite lens-flare en croix au centre. API : `setState(state)`, `setVolume(0..1)`, `triggerDemo()`. Couleurs/vitesses changent selon l'état.
- **`screen_capture.ts`** : `getDisplayMedia` + `ImageCapture.grabFrame` → JPEG base64 envoyé au backend.

Pas de tsconfig (le build skip `tsc`), mais `frontend/vite.config.ts` existe (multi-pages : `index.html` orbe + `dashboard.html` config). Dépendances runtime : `three` (orbe) + `d3-force` (graphe mémoire du dashboard) ; devDeps : `typescript`, `vite`, `@types/three`, `@types/d3-force`.

### Mobile (`mobile/`)

HTML statique + `app.js`. Utilise **Web Speech API** native du navigateur pour STT et TTS (pas d'edge-tts ni de pygame côté mobile). WebSocket dynamique : `ws://${window.location.hostname}:8765` pour fonctionner sur LAN. Quand le mobile envoie `mobile_command`, le backend met `_skip_pc_audio=True` pour ne pas dupliquer l'audio.

**Accès distant via Tailscale** (`jarvis_actions/tailscale_net.py`) : le panneau « Appairage mobile » du dashboard (`_payload_appairage`) affiche, en plus du lien LAN, un **lien Tailscale** (`http://<ip-tailnet>:8080/?token=…`) dès qu'une IP du tailnet (plage CGNAT `100.64.0.0/10`) est détectée — via la CLI `tailscale ip -4` puis repli sur le scan des interfaces (`psutil`). Permet de piloter Jarvis depuis le téléphone **de n'importe où** (tél + PC sur le même compte Tailscale), pas seulement sur le Wi-Fi local. Détection en dégradation propre (rien si Tailscale absent + guide d'install affiché). `_ip_dans_plage_tailscale` est pur et testé.

## Configuration

`.env` (lu par `python-dotenv`) :
```
GEMINI_API_KEY, YOUTUBE_API_KEY, XAI_API_KEY, HA_URL, HA_TOKEN, SERPAPI_API_KEY, GROQ_API_KEY
```

**Identité utilisateur** : `jarvis_config.py` expose `USER_NAME`, lu depuis `JARVIS_USER_NAME` (.env, défaut `"Monsieur"`). Importé par `main2.py` et les modules `jarvis_actions/`. Toutes les phrases de Jarvis utilisent `{USER_NAME}` — ne jamais réintroduire de prénom en dur.

**Config Home Assistant perso** : les entités domotique (`PIECES_LUMIERES`, `PIECES_CAPTEURS`, `APPAREILS_BATTERIE`, etc.) sont externalisées dans `jarvis_home_config.py` (**gitignoré**, valeurs réelles) avec repli auto sur `jarvis_home_config_example.py` (générique, versionné). `main2.py` les importe via `try/except ImportError`. Ne jamais committer `jarvis_home_config.py`.

**Données perso gitignorées avec modèle versionné** (les modèles `*_example.json` sont regroupés dans `examples/`) : `jarvis_profile.json` (famille, adresse, habitudes — modèle `examples/jarvis_profile_example.json`), `jarvis_mcp.json` (modèle `examples/jarvis_mcp_example.json`), `jarvis_ui_config.json` (thème, couleur de l'orbe, dossier Cowork — modèle `examples/jarvis_ui_config_example.json`), `jarvis_skills/skills_config.json` (état actif/inactif des skills). Ne jamais les committer ni mettre de vraies données dans les exemples.

Variables d'env optionnelles :
- `JARVIS_USER_NAME` — prénom utilisé par Jarvis (défaut `Monsieur`)
- `FORCE_OLLAMA=1` — force le mode local même si Gemini est dispo
- `JARVIS_NO_BROWSER=1` — désactive l'auto-launch Vite + navigateur ; sert `frontend/dist/` (build prod) directement sur le port 5173. Utilisé par `jarvis_desktop.py` et le `.exe`.
- `JARVIS_HEADLESS=1` — **mode serveur (Docker)** : désactive la boucle vocale (micro) et la sortie audio locale (pygame), garde WS/HTTP/frontend. Implique `JARVIS_NO_BROWSER`, fait écouter le frontend statique sur `0.0.0.0`, saute le hotkey clavier. Le STT/TTS se fait côté navigateur. Les imports `pyautogui`/`pyaudio`/`pygame`/`speech_recognition` sont rendus optionnels (→ `None` si absents) pour permettre le boot Linux sans périphérique.
- `OLLAMA_URL` — URL du serveur Ollama (défaut `http://127.0.0.1:11434`, ex. Docker `http://ollama:11434`). Lu par `main2.py`, `memory_rag.py`, `model_advisor_service.py`.
- `OPENCLAW_URL` / `OPENCLAW_TOKEN` / `OPENCLAW_HOOKS_TOKEN` / `OPENCLAW_AGENT_ID` — pont OpenClaw (voir `jarvis_actions/openclaw.py`)
- `PYTHONUNBUFFERED=1` — recommandé en debug pour voir les logs immédiatement

Sans clé valide, `_cle_valide()` détecte les placeholders `VOTRE_API` / `VOTRE_CLE_ICI` et désactive le client correspondant.

## Pièges connus

- **Modules Python dans `jarvis_core/` (dossier source PLAT, pas un package)** : tous les `.py` du cœur (main2, jarvis_config, jarvis_dashboard_api, jarvis_profile, jarvis_version, jarvis_desktop, jarvis_web…) vivent dans `jarvis_core/`. On garde les imports **à plat** (`from jarvis_config import …`) : `jarvis_core/` est ajouté à `sys.path`, il n'y a **PAS** de `__init__.py` ni d'imports `jarvis_core.X`. En dev, lancer **depuis la racine** (`python jarvis_core/main2.py`) ; les entry-points (main2/desktop/web) ajoutent `jarvis_core/` ET la racine à sys.path (la racine pour `jarvis_actions`/`jarvis_skills`/`jarvis_home_config`). Tooling : garder les **noms plats** — specs (`pathex` inclut `jarvis_core/`, hiddenimports/excludes en noms plats), CI/installateur (`sys.path.insert(0,'jarvis_core')` ou `jarvis_core\jarvis_version.py`), tests (`pytest.ini` `pythonpath = . jarvis_core` + `tests/conftest.py`). **`_dossier_donnees()` en dev remonte `.parent.parent`** (jarvis_core/ → racine) pour garder `.env`/mémoire/profil/`frontend`/`mobile` à la racine ; en frozen, PyInstaller aplatit tout, donc `sys.executable` ET `__file__`(=`_MEIPASS`) restent inchangés. Nouveau module core → le placer dans `jarvis_core/`, et toute résolution `Path(__file__).parent` qui visait la racine doit remonter d'un cran **en dev uniquement**.
- **Persistance en mode .exe : pattern `_dossier_donnees()` OBLIGATOIRE** : en frozen, ne jamais se fier au cwd ni à `Path(__file__).parent` (= `_internal/` en onedir, ou l'ancien `sys._MEIPASS` temporaire effacé à la sortie en onefile). Tout fichier lu/écrit au runtime (`.env`, `jarvis_memoire.json`, `jarvis_historique.json`, `jarvis_mcp.json`, `token.pickle`, profil, routines...) doit être résolu à côté de l'exe via `Path(sys.executable).parent` quand `sys.frozen` (cf. `jarvis_profile._dossier_donnees`) — sinon données perdues à chaque fermeture du .exe.
- **Builds onedir, deux exes UN SEUL dossier** : `Jarvis.spec`/`JarvisWeb.spec` produisent du **onedir** (et non onefile) pour éviter les faux positifs antivirus (en onefile, l'auto-extraction runtime dans un dossier temp = heuristique « dropper » → `Trojan:Win32/Wacatac.B!ml`). Les deux exes DOIVENT rester dans le même dossier (`{app}`) pour partager `.env`/mémoire/profil (`_dossier_donnees()` = `Path(sys.executable).parent`) ; ils cohabitent grâce à des `contents_directory` DISTINCTS (`_internal` pour Jarvis, `_internal_web` pour JarvisWeb). `build_all.bat` et l'étape installateur de `release.yml` déversent `dist/Jarvis/*` et `dist/JarvisWeb/*` à la racine ; l'`.iss` copie les deux `_internal*`. Ne JAMAIS revenir à `--onefile` ni activer UPX (réintroduit les FP). PyInstaller est **pinné** dans `requirements-windows.txt` (FP variables selon la version — A/B-tester sur VirusTotal avant de bumper).
- **Les specs refusent de builder si les deps manquent** : garde-fou `find_spec` en tête de `Jarvis.spec`/`JarvisWeb.spec` (sinon PyInstaller "réussit" et produit un .exe qui crashe en ModuleNotFoundError). Installer `requirements-windows.txt` d'abord.
- **Aucun secret dans les binaires** : `.env`, `credentials.json`, `jarvis_memoire.json` et `jarvis_home_config.py` (excludes) ne sont PAS embarqués dans les .exe — ils vivent à côté du binaire. Ne jamais les rajouter aux `datas`.
- **Conflit de port 8765** : si une instance Python orpheline tourne, le nouveau bind échoue silencieusement et le frontend reste en "reconnexion". Vérifier avec `Get-NetTCPConnection -LocalPort 8765`.
- **Vite sur 5174** : si le 5173 est déjà pris (ancienne instance npm pas tuée), Vite démarre sur 5174 mais main2.py ouvre `localhost:5173` dans le navigateur — ouvrir 5174 manuellement ou tuer l'ancien node.
- **Premier appel Ollama lent** : ~25-30s le temps de charger le modèle en RAM, ensuite 2-5s.
- **Encoding** : sous Windows utiliser `PYTHONIOENCODING=utf-8` sinon les caractères accentués des prints peuvent crasher.
- **Ne pas amender les commits** : règle utilisateur globale, toujours créer un nouveau commit.
- **`pc_actions` / `dev_actions` court-circuitent l'IA** : si tu ajoutes un nouveau mot-clé qui matche déjà un alias existant, la commande ne touchera jamais Gemini/Ollama. Inversement, si une commande "intelligente" est interceptée par erreur, vérifier les regex dans ces deux fichiers en premier.
- **`jarvis_tray.py` / `jarvis_desktop.py` lancent `main2.py` en sous-process** : tuer la fenêtre tray ne tue pas forcément le backend ; vérifier `Get-Process python` si comportement bizarre au redémarrage.
- **`Jarvis.exe` (PyInstaller) importe `main2` en thread du même process** (détection `sys.frozen`), pas de subprocess. À chaque modif de `main2.py` ou des deps, il faut rebuild : `python -m PyInstaller Jarvis.spec --clean --noconfirm`. Build ~1 min, sortie onedir `dist/Jarvis/` (exe + `_internal/`).
- **Mode arrière-plan du `.exe`** : `jarvis_desktop.py` crée la fenêtre webview avec `hidden=True` puis lance un client WS qui écoute `set_state` du backend. État `idle` → cache la fenêtre après 3s ; tout autre état → affiche la mini-fenêtre orbe centrée au-dessus de la barre des tâches. Menu tray "Ouvrir l'interface" affiche la fenêtre complète (980×720, ne se cache pas auto).
- **Ne pas exclure `unittest` dans `Jarvis.spec`** : `pyparsing` (dépendance transitive de `googleapiclient`) en a besoin sinon crash au démarrage du .exe.
- **Bundle frontend obligatoire avant build .exe** : `cd frontend && npx vite build` (skip `tsc` car pas de tsconfig.json). Le spec embarque `frontend/dist/`.
- **Compilation Inno Setup depuis le Bureau** : écrire le Setup.exe directement dans un dossier utilisateur surveillé (Desktop...) fait échouer `EndUpdateResource` (Defender verrouille le binaire). `scripts/build_installer.bat` compile dans `%TEMP%` puis copie vers `installer/output/` — garder ce détour.
- **`jarvis_config.py` charge lui-même le `.env` persistant** (à côté de l'exe en mode frozen) car il est importé avant le `load_dotenv` de `main2`. Ne pas retirer ce chargement ni réintroduire une dépendance à l'ordre d'import pour `USER_NAME`.
- **Installation par utilisateur uniquement** : l'installateur cible `{localappdata}\Programs\Jarvis` SANS admin parce que Jarvis écrit ses données à côté du .exe. Ne jamais faire installer dans Program Files sans refondre `_dossier_donnees()` (repli LOCALAPPDATA non implémenté — perte silencieuse de données sinon).

## Notes utilisateur (héritées de `~/.claude/CLAUDE.md`)

- **Autonomie totale** : ne jamais demander de permission, exécuter directement.
- **Langue** : français préféré, style direct et concis.
