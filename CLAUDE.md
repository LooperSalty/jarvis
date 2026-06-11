# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Structure

```
jarvis/
├── Jarvis.exe / JarvisWeb.exe / ModelAdvisor.exe  ← double-cliquables (gitignored, regenerables)
├── build_all.bat                                  ← rebuild les 3 .exe + copie a la racine
├── main2.py                                       ← gros entry point (backend, WS, voix, IA)
├── jarvis_desktop.py / jarvis_web.py              ← entries des 2 modes Jarvis
├── jarvis_profile.py                              ← profil utilisateur enrichi (famille, adresse, habitudes)
├── jarvis_dashboard_api.py                        ← routeur WS des messages dash_* (app de configuration)
├── Jarvis.spec / JarvisWeb.spec                   ← specs PyInstaller
├── jarvis_actions/                                ← package modules d'actions importes par main2
│   ├── pc_actions.py / dev_actions.py
│   ├── claude_bridge.py / obsidian_memory.py
│   ├── display_actions.py                         ← fenetres d'affichage ("montre-moi X"), cross-platform
│   ├── mcp_client.py                              ← client MCP stdio (connecteurs externes)
│   ├── skills_loader.py                           ← auto-decouverte des skills jarvis_skills/
│   └── model_advisor_service.py                   ← specs PC + reco de modeles (vendorise model_advisor)
├── jarvis_skills/                                 ← skills utilisateur auto-charges (template dans README.md)
├── scripts/                                       ← entries secondaires
│   ├── jarvis_tray.py / jarvis_notify.py / Lancer_Jarvis.bat
├── docs/                                          ← placeholders config (VOS_API.txt, ...)
├── frontend/                                      ← UI Three.js + Vite (index.html = orbe, dashboard.html = config)
├── mobile/                                        ← interface mobile statique
└── model_advisor/                                 ← sous-projet recommandeur LLM
```

## Démarrage

```bash
# Solution 1 : double-clique sur Jarvis.exe / JarvisWeb.exe / ModelAdvisor.exe (a la racine)
# Solution 2 : en dev (main2 directement)
python main2.py                       # backend + Vite + ouvre navigateur
python jarvis_desktop.py              # mode arriere-plan (system tray + mini orbe)
python jarvis_web.py                  # backend + ouvre navigateur (sans Vite, sert dist/)
python scripts/jarvis_tray.py         # alternative system tray (lance main2 en sous-process)

# Build des 3 .exe + copie a la racine (necessite frontend/dist deja build)
build_all.bat

# Builds individuels
python -m PyInstaller Jarvis.spec --clean --noconfirm           # Jarvis.exe ~250 MB
python -m PyInstaller JarvisWeb.spec --clean --noconfirm        # JarvisWeb.exe ~150 MB
cd model_advisor && python -m PyInstaller --onefile --windowed --name ModelAdvisor --clean --noconfirm model_advisor.py

# Frontend seul (dev avec HMR)
cd frontend && npm run dev          # http://localhost:5173

# Dépendances
python -m pip install -r requirements.txt
cd frontend && npm install

# Mode 100% local (force Ollama, ignore les clés cloud)
FORCE_OLLAMA=1 python main2.py
ollama serve && ollama pull llama3.2:3b
```

Le `.bat` `DÉMARRER_JARVIS.bat` (non versionné) contient un chemin Python codé en dur et n'est pas portable — utilise `python main2.py` directement (ou `scripts/Lancer_Jarvis.bat` qui est plus simple).

Pas de tests automatisés, pas de linter configuré. La seule étape de build est `cd frontend && npm run build` (TypeScript + Vite production).

### Envoyer une commande depuis l'extérieur

`jarvis_notify.py` est un client WebSocket CLI minimal qui se connecte à `ws://localhost:8765` :
```bash
python jarvis_notify.py "message a vocaliser"          # type=tell par defaut
python jarvis_notify.py --type cmd "ouvre chrome"      # comme une commande mobile
```
Pratique depuis hooks, scripts, ou autres process pour piloter Jarvis sans passer par la voix.

## Architecture

**`main2.py` (2528 lignes) est le point d'entrée monolithique.** Il orchestre :

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

Page Vite séparée `frontend/dashboard.html` (sources `frontend/src/dashboard/`), accessible sur `http://localhost:5173/dashboard.html`, via le lien ⚙ de l'orbe, ou les entrées "Configuration" des menus tray. 6 sections : Vue d'ensemble (clés API présentes/absentes — jamais les valeurs —, intégrations, nom utilisateur), Profil (famille/adresse/habitudes/routines → injecté dans le system prompt par `jarvis_profile.contexte_profil()`), Mémoire (graphe d3-force sur canvas via `graph.ts` + CRUD), Chat (réutilise `text_command`/`chat_message`), Connecteurs (serveurs MCP + skills), Modèle IA (specs PC + reco Ollama).

- **Protocole** : tout passe par le WS 8765, messages `dash_*` (contrat complet en tête de `jarvis_dashboard_api.py` et `frontend/src/dashboard/ws.ts`).
- **`jarvis_dashboard_api.py`** : routeur injecté par `init_api(contexte)` depuis main2 (callables mémoire + user_name). Écrit le `.env` ATOMIQUEMENT avec liste blanche de clés (`CLES_GEREES`) ; ne renvoie JAMAIS une valeur de clé au client (booléens uniquement). `restart_required` devient `True` après tout `dash_set_env`.
- **MCP** (`jarvis_actions/mcp_client.py`) : client stdio JSON-RPC sans dépendance, config `jarvis_mcp.json` (gitignoré, modèle `jarvis_mcp_example.json`). Les tools des serveurs `enabled` sont exposés à la boucle agent Gemini au démarrage (`_init_mcp_tools` dans main2, noms `mcp_<serveur>_<tool>`). Les sessions vivent sur l'event loop du serveur WS — toujours awaiter depuis ce loop.
- **Skills** (`jarvis_skills/*.py`) : auto-découverts par `skills_loader`, contrat `SKILL = {...}` + `executer(cmd) -> (str|None, bool)` (ou `async_executer`). Branchés dans `traiter_reponse_ia` AVANT `pc_actions`. En mode .exe, un skill peut être déposé à côté du binaire sans rebuild.
- **Affichage** (`display_actions.py`) : `montrer_contenu(titre, contenu, type)` génère une carte HTML sombre dans `%TEMP%/jarvis_affichage/` et l'ouvre (startfile / `open` / `xdg-open`). Exposé à l'agent Gemini comme tool `show_content` ("montre-moi...").
- **Modèles** (`model_advisor_service.py`) : copie vendorisée de la base de `model_advisor/model_advisor.py` (commentaire "Synchronise depuis..." — mettre à jour les deux), détection specs cross-platform, reco top 8 + flag `installe` via Ollama `/api/tags`.

### Modules d'actions (importés par `main2.py`)

Détection locale par mots-clés AVANT tout appel IA — économise des appels Gemini/Ollama :

- **`pc_actions.py`** : ouvre/ferme apps Windows (`chrome`, `vscode`, `discord`...), navigue sites (`youtube`, `gmail`, `google maps`...), capture d'écran, contrôle souris/clavier via `pyautogui`. Mappings dans `_APP_ALIASES` et `_WEB_SHORTCUTS`. Retourne `(reponse, success)` ou `(None, False)` si non reconnu.
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

Pas de tsconfig, pas de vite.config — Vite utilise les défauts. `package.json` ne dépend que de `three`, `vite`, et `typescript`.

### Mobile (`mobile/`)

HTML statique + `app.js`. Utilise **Web Speech API** native du navigateur pour STT et TTS (pas d'edge-tts ni de pygame côté mobile). WebSocket dynamique : `ws://${window.location.hostname}:8765` pour fonctionner sur LAN. Quand le mobile envoie `mobile_command`, le backend met `_skip_pc_audio=True` pour ne pas dupliquer l'audio.

## Configuration

`.env` (lu par `python-dotenv`) :
```
GEMINI_API_KEY, YOUTUBE_API_KEY, XAI_API_KEY, HA_URL, HA_TOKEN, SERPAPI_API_KEY, GROQ_API_KEY
```

**Identité utilisateur** : `jarvis_config.py` expose `USER_NAME`, lu depuis `JARVIS_USER_NAME` (.env, défaut `"Monsieur"`). Importé par `main2.py` et les modules `jarvis_actions/`. Toutes les phrases de Jarvis utilisent `{USER_NAME}` — ne jamais réintroduire de prénom en dur.

**Config Home Assistant perso** : les entités domotique (`PIECES_LUMIERES`, `PIECES_CAPTEURS`, `APPAREILS_BATTERIE`, etc.) sont externalisées dans `jarvis_home_config.py` (**gitignoré**, valeurs réelles) avec repli auto sur `jarvis_home_config_example.py` (générique, versionné). `main2.py` les importe via `try/except ImportError`. Ne jamais committer `jarvis_home_config.py`.

**Données perso gitignorées avec modèle versionné** : `jarvis_profile.json` (famille, adresse, habitudes — modèle `jarvis_profile_example.json`), `jarvis_mcp.json` (modèle `jarvis_mcp_example.json`), `jarvis_skills/skills_config.json` (état actif/inactif des skills). Ne jamais les committer ni mettre de vraies données dans les exemples.

Variables d'env optionnelles :
- `JARVIS_USER_NAME` — prénom utilisé par Jarvis (défaut `Monsieur`)
- `FORCE_OLLAMA=1` — force le mode local même si Gemini est dispo
- `JARVIS_NO_BROWSER=1` — désactive l'auto-launch Vite + navigateur ; sert `frontend/dist/` (build prod) directement sur le port 5173. Utilisé par `jarvis_desktop.py` et le `.exe`.
- `OPENCLAW_URL` / `OPENCLAW_TOKEN` / `OPENCLAW_HOOKS_TOKEN` / `OPENCLAW_AGENT_ID` — pont OpenClaw (voir `jarvis_actions/openclaw.py`)
- `PYTHONUNBUFFERED=1` — recommandé en debug pour voir les logs immédiatement

Sans clé valide, `_cle_valide()` détecte les placeholders `VOTRE_API` / `VOTRE_CLE_ICI` et désactive le client correspondant.

## Pièges connus

- **Conflit de port 8765** : si une instance Python orpheline tourne, le nouveau bind échoue silencieusement et le frontend reste en "reconnexion". Vérifier avec `Get-NetTCPConnection -LocalPort 8765`.
- **Vite sur 5174** : si le 5173 est déjà pris (ancienne instance npm pas tuée), Vite démarre sur 5174 mais main2.py ouvre `localhost:5173` dans le navigateur — ouvrir 5174 manuellement ou tuer l'ancien node.
- **Premier appel Ollama lent** : ~25-30s le temps de charger le modèle en RAM, ensuite 2-5s.
- **Encoding** : sous Windows utiliser `PYTHONIOENCODING=utf-8` sinon les caractères accentués des prints peuvent crasher.
- **Ne pas amender les commits** : règle utilisateur globale, toujours créer un nouveau commit.
- **`pc_actions` / `dev_actions` court-circuitent l'IA** : si tu ajoutes un nouveau mot-clé qui matche déjà un alias existant, la commande ne touchera jamais Gemini/Ollama. Inversement, si une commande "intelligente" est interceptée par erreur, vérifier les regex dans ces deux fichiers en premier.
- **`jarvis_tray.py` / `jarvis_desktop.py` lancent `main2.py` en sous-process** : tuer la fenêtre tray ne tue pas forcément le backend ; vérifier `Get-Process python` si comportement bizarre au redémarrage.
- **`Jarvis.exe` (PyInstaller) importe `main2` en thread du même process** (détection `sys.frozen`), pas de subprocess. À chaque modif de `main2.py` ou des deps, il faut rebuild : `python -m PyInstaller Jarvis.spec --clean --noconfirm`. Build ~1 min, .exe ~150 MB.
- **Mode arrière-plan du `.exe`** : `jarvis_desktop.py` crée la fenêtre webview avec `hidden=True` puis lance un client WS qui écoute `set_state` du backend. État `idle` → cache la fenêtre après 3s ; tout autre état → affiche la mini-fenêtre orbe centrée au-dessus de la barre des tâches. Menu tray "Ouvrir l'interface" affiche la fenêtre complète (980×720, ne se cache pas auto).
- **Ne pas exclure `unittest` dans `Jarvis.spec`** : `pyparsing` (dépendance transitive de `googleapiclient`) en a besoin sinon crash au démarrage du .exe.
- **Bundle frontend obligatoire avant build .exe** : `cd frontend && npx vite build` (skip `tsc` car pas de tsconfig.json). Le spec embarque `frontend/dist/`.

## Notes utilisateur (héritées de `~/.claude/CLAUDE.md`)

- **Autonomie totale** : ne jamais demander de permission, exécuter directement.
- **Langue** : français préféré, style direct et concis.
