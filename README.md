# J.A.R.V.I.S — Assistant dev personnel local

> 🇬🇧 **English version: [README.en.md](README.en.md)**

Assistant vocal qui tourne en arrière-plan sur Windows, avec une orbe Three.js comme interface et un LLM 100% local (Ollama) pour le cerveau. Pensé pour un dev qui veut gagner du temps : ouverture rapide de projets, git, notes, intégration Claude Code, mémoire persistante synchronisée avec Obsidian.

## Installation (utilisateur final — Windows)

**Aucun prérequis** : pas besoin de Python, Node ni d'aucun runtime. L'installateur graphique s'occupe de tout, même sur un Windows vierge.

1. Télécharge **`JarvisSetup-x.y.z.exe`** depuis la [dernière release](https://github.com/LooperSalty/jarvis/releases/latest)
2. Lance-le et laisse-toi guider (assistant en français ou anglais) :
   - choix des composants : **Jarvis** (app principale), **JarvisWeb** (mode navigateur), **ModelAdvisor** (quel modèle pour mon PC ?)
   - **Cerveau IA local** (recommandé) : l'installateur télécharge et installe **Ollama** automatiquement, puis le **modèle de ton choix** (llama3.2:3b léger / qwen2.5:7b qualité / deepseek-coder-v2:lite code) — la progression s'affiche en direct
   - options : raccourci bureau, lancement au démarrage de Windows
3. C'est tout. Jarvis démarre, l'orbe apparaît, et tu configures le reste (clés API optionnelles, profil, nom d'utilisateur) dans le **dashboard** intégré (menu tray → Configuration).

Notes :
- L'installation se fait **par utilisateur** (`%LOCALAPPDATA%\Programs\Jarvis`), sans droits admin. Jarvis stocke ses données (mémoire, profil, `.env`) **à côté de son `.exe`** : ne le déplace pas dans un dossier non inscriptible type `Program Files`.
- Pas de réseau pendant l'installation ? Jarvis s'installe quand même ; tu pourras installer Ollama plus tard depuis [ollama.com](https://ollama.com), puis un modèle depuis le dashboard (section « Modèle IA »).
- La désinstallation (Panneau de configuration → Jarvis) propose de conserver ou supprimer tes données.
- Mise à jour : le dashboard et le menu tray (« Vérifier les mises à jour ») détectent les nouvelles releases GitHub.

## Fonctionnalités

- **Voix** : reconnaissance française + TTS edge-tts (voix `fr-FR-HenriNeural`), wake-word "Jarvis"
- **Cerveau local** : Ollama avec `qwen2.5:7b` (fallback `llama3.2:3b`, `deepseek-coder-v2:lite`)
- **Streaming TTS phrase par phrase** : les blocs de code ne sont pas vocalisés (juste affichés dans le panneau chat)
- **Orbe 3D** : ~9000 particules sur courbes Lissajous animées, réagit à l'état (idle / listening / thinking / speaking) et au volume vocal
- **Mémoire persistante** : faits stockés dans `jarvis_memoire.json` ET synchronisés avec un vault Obsidian (`Jarvis/Memoire/*.md`, éditables à la main)
- **Historique** : conversations sauvegardées + consultables dans le panneau chat (par jour)
- **Pont Claude Code bidirectionnel** : `/jarvis <message>` depuis Claude Code pour parler à Jarvis ; *"Jarvis demande à Claude Code..."* pour l'inverse
- **Surveillance d'inactivité Claude Code** : Jarvis te notifie si tu n'as pas relancé Claude depuis X jours
- **Actions PC instantanées** (sans IA) : ouvrir Chrome / VSCode / Spotify / Obsidian / Google Maps / YouTube / etc., volume, capture, mute, copier/coller, taper du texte
- **Actions dev** : ouvrir un projet dans VSCode, git status / log du jour, terminal sur un dossier, timer/pomodoro, note rapide vers Obsidian, lecture du presse-papier
- **System tray Windows** : icône bleue dans la zone de notification, click pour ouvrir l'orbe, vérification de mise à jour intégrée
- **Raccourci global Ctrl+Shift+J** : ramène la fenêtre Jarvis au premier plan depuis n'importe quelle app
- **Push-to-talk** : maintiens **Espace** dans la page web pour parler sans dire "Jarvis"
- **Input texte** : champ de saisie en bas de l'orbe pour taper en silence
- **Mute persistant** : un clic = mute, jusqu'au prochain clic
- **Mobile** : interface HTML séparée servie sur `:8080`, utilise Web Speech API native du tél
- **Dashboard de configuration** : vraie app de config sur `http://localhost:5173/dashboard.html` (lien ⚙ sur l'orbe, ou menu tray "Configuration") — profil utilisateur (famille, adresse, habitudes injectés dans le cerveau), clés API (présentes/absentes, jamais affichées), mémoire visualisée en graphe interactif, chat écrit, connecteurs MCP, skills, version installée + lien de mise à jour, et test "quel modèle Ollama pour mon PC ?" (détection RAM/GPU + recommandations + installation en un clic)
- **Fenêtres d'affichage** : *"Jarvis, montre-moi..."* — Jarvis ouvre une carte HTML sombre (Windows/macOS/Linux) pour montrer listes, comparatifs, images, liens
- **Connecteurs MCP** : branche des serveurs Model Context Protocol (stdio) via le dashboard, leurs tools deviennent utilisables par l'agent
- **Pont OpenClaw** : lie Jarvis à ton agent [OpenClaw](https://docs.openclaw.ai) local — *"demande à openclaw de résumer mes messages whatsapp"* (réponse vocalisée), *"envoie à openclaw..."* (tâche de fond, réponse sur tes messageries), *"statut openclaw"*. Config : `OPENCLAW_TOKEN` / `OPENCLAW_HOOKS_TOKEN` dans le dashboard
- **Skills** : dépose un `.py` dans `jarvis_skills/` (template dans le README du dossier), Jarvis le charge tout seul — même à côté du `.exe`

## Démarrage (développeur)

```bash
# Installer les deps Python + frontend
python -m pip install -r requirements-windows.txt   # set runtime épuré Windows
cd frontend && npm install && cd ..

# Lancer Ollama et un modèle
ollama serve
ollama pull qwen2.5:7b

# Mode tray (recommandé)
python scripts/jarvis_tray.py

# Ou mode desktop standalone (fenêtre frameless PyQt5)
python jarvis_core/jarvis_desktop.py

# Ou backend brut (avec Vite auto-lancé)
python jarvis_core/main2.py
```

> `requirements.txt` est un freeze complet de la machine de dev (pins en conflit) :
> **ne pas l'utiliser sur un env vierge** — `requirements-windows.txt` est la liste curatée.

### Builds Windows (.exe + installateur)

```bash
# Les 3 binaires (Jarvis.exe, JarvisWeb.exe, ModelAdvisor.exe) + copie à la racine
build_all.bat

# L'installateur JarvisSetup-x.y.z.exe (nécessite Inno Setup 6 :
#   winget install JRSoftware.InnoSetup)
scripts\build_installer.bat
# → installer\output\JarvisSetup-<version>.exe
```

### macOS

`jarvis_core/jarvis_desktop.py` reste Windows-first (PyQt5 WebEngine + win32api). Sur macOS, utilise le mode web/backend :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
brew install portaudio
python -m pip install -r requirements-macos.txt
cd frontend && npm install && cd ..
python jarvis_core/main2.py
```

Notes :
- Sur macOS, l'interface fiable est `http://localhost:5173` via `main2.py` ou `jarvis_web.py`.
- Certaines actions système sont adaptées (`open`, Terminal, presse-papier, raccourcis Command), mais les automatisations vocales peuvent demander les permissions macOS Accessibilité, Microphone et Enregistrement de l'écran.

Le backend ouvre 3 ports :
- `:8765` WebSocket (frontend ↔ backend)
- `:5173` Vite (frontend Three.js)
- `:8080` HTTP (interface mobile)

### Docker (mode serveur headless)

Pour faire tourner Jarvis en conteneur (serveur Linux, NAS, VM…). Un conteneur n'a ni micro, ni haut-parleur, ni interface graphique : le backend tourne en **mode headless** (`JARVIS_HEADLESS=1`) et le **STT/TTS se fait côté navigateur** (Web Speech API) via l'UI web ou mobile. La boucle vocale locale et l'audio pygame sont désactivés ; tout le reste (chaîne IA Gemini/Groq/Grok/Ollama, dashboard, connecteurs, mobile) fonctionne.

```bash
# 1. Renseigner les clés API (au minimum GEMINI_API_KEY, ou rien pour Ollama)
cp .env.example .env        # puis éditer .env

# 2a. Backend seul (cerveau cloud)
docker compose up -d --build

# 2b. Ou avec Ollama embarqué (100% local, profil "local")
docker compose --profile local up -d --build
docker compose exec ollama ollama pull qwen2.5:7b   # 1re fois : télécharger un modèle
```

Puis ouvrir :
- **UI orbe + dashboard** : http://localhost:5173 (dashboard sur `/dashboard.html`)
- **UI mobile** : http://localhost:8080
- WebSocket : `ws://localhost:8765`

Sans Compose :

```bash
docker build -t jarvis .
docker run -d --env-file .env -p 5173:5173 -p 8765:8765 -p 8080:8080 jarvis
```

Notes :
- L'image utilise **`requirements-docker.txt`** (set minimal Linux), **pas** `requirements.txt`.
- Mode local : le service `jarvis` doit pointer vers le conteneur Ollama — décommente `OLLAMA_URL: "http://ollama:11434"` dans `docker-compose.yml`.
- Le code est figé dans l'image : rebuild (`docker compose up -d --build`) après toute modif. Persistance mémoire/profil : voir les binds commentés dans `docker-compose.yml`.

## Configuration

Copier `.env.example` vers `.env` et remplir les clés dont tu as besoin — ou tout faire depuis le **dashboard** (section Vue d'ensemble), qui écrit le `.env` pour toi. **Aucune clé n'est obligatoire** : sans clé Gemini valide, Jarvis bascule automatiquement sur Ollama.

- **Nom d'utilisateur** : Jarvis t'appelle "Monsieur" par défaut. Définis `JARVIS_USER_NAME` (dashboard ou `.env`) pour qu'il utilise ton prénom.
- **Home Assistant** (optionnel) : les entités domotique (lumières, capteurs, batteries...) sont déclarées dans `jarvis_home_config.py`. Copie `jarvis_home_config_example.py` vers `jarvis_home_config.py` et remplace les `entity_id` par les tiens (ce fichier est ignoré par git, il ne contient que TES entités). Sans ce fichier, Jarvis utilise les exemples génériques.
- **Secrets** : les clés sensibles vont dans le coffre système (keyring) quand il est disponible ; le `.env` reçoit une ACL restreinte à ton compte utilisateur.

```bash
# Forcer le mode local même avec une clé Gemini valide
FORCE_OLLAMA=1 python scripts/jarvis_tray.py
```

## Tests

Suite **pytest** (`tests/`) lancée par la CI sur chaque PR :

```bash
python -m pytest
```

## Architecture

`main2.py` (~4300 lignes) est le point d'entrée monolithique. Il orchestre :

1. **WebSocket** sur `:8765` — multiplexe les clients (web, mobile, dashboard, tray)
2. **HTTP** sur `:8080` pour le frontend mobile
3. **Auto-launch Vite** sur `:5173`
4. **Boucle voix** : reconnaissance, wake-word, TTS
5. **Pipeline de commande** :
   - Résolution locale (math, français, conversion, traduction)
   - Vision écran (Gemini multimodal si dispo)
   - **Actions dev** (`dev_actions.py`) — projets, git, timer, notes
   - **Actions PC** (`pc_actions.py`) — applis, web shortcuts, volume, etc.
   - **Connecteurs** — Spotify, Meross, navigateur Playwright, OpenClaw, MCP
   - **Pont Claude Code** — *"demande à Claude Code..."*
   - **Streaming Ollama + TTS phrase par phrase**

Modules clés :
- `main2.py` — orchestration
- `jarvis_dashboard_api.py` — routeur WS du dashboard de configuration
- `jarvis_version.py` — version + check de mise à jour (releases GitHub)
- `jarvis_actions/` — actions PC/dev, connecteurs, voix locale, routines, RAG
- `installer/JarvisSetup.iss` — installateur Windows (Inno Setup)
- `frontend/src/main.ts` — WebSocket client + UI
- `frontend/src/orb.ts` — rendu Three.js
- `frontend/src/dashboard/` — app de configuration
- `mobile/app.js` — interface mobile (Web Speech API)

## Stack

- **Python 3.12** : websockets, edge-tts, pygame, speech_recognition, pyautogui, google-genai
- **Ollama** : qwen2.5:7b (chat), llama3.2:3b (rapide), deepseek-coder-v2:lite (code)
- **Frontend** : Vite + TypeScript + Three.js (sans framework UI)
- **Desktop** : PyQt5 + QtWebEngine (fenêtre frameless + tray + mini-orbe)
- **Hotkey global** : keyboard + pygetwindow
- **Packaging** : PyInstaller (.exe) + Inno Setup (installateur)

## Releases

Pousser un tag `vX.Y.Z` déclenche `.github/workflows/release.yml` : build du bundle frontend, des binaires Windows (`Jarvis.exe`, `JarvisWeb.exe`, `ModelAdvisor.exe`), de **l'installateur `JarvisSetup-x.y.z.exe`** (Inno Setup) et du binaire macOS (mode web, best-effort), puis publication d'une release GitHub avec les artefacts. Bumper `VERSION` dans `jarvis_version.py` (et `version_info.txt`) en même temps que le tag.

```bash
# Exemple
git tag v0.2.0 && git push origin v0.2.0
```

`jarvis_version.check_update()` interroge l'API GitHub ; le dashboard et le menu tray signalent la nouvelle version.

## Licence

Personnel, pas de licence ouverte pour le moment.
