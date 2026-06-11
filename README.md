# J.A.R.V.I.S — Assistant dev personnel local

Assistant vocal qui tourne en arriere-plan sur Windows, avec une orbe Three.js comme interface et un LLM 100% local (Ollama) pour le cerveau. Pense pour un dev qui veut gagner du temps : ouverture rapide de projets, git, notes, integration Claude Code, memoire persistante synchronisee avec Obsidian.

## Fonctionnalites

- **Voix** : reconnaissance francaise + TTS edge-tts (voix `fr-FR-HenriNeural`), wake-word "Jarvis"
- **Cerveau local** : Ollama avec `qwen2.5:7b` (fallback `llama3.2:3b`, `deepseek-coder-v2:lite`)
- **Streaming TTS phrase par phrase** : les blocs de code ne sont pas vocalises (juste affiches dans le panneau chat)
- **Orbe 3D** : ~9000 particules sur courbes Lissajous animees, reagit a l'etat (idle / listening / thinking / speaking) et au volume vocal
- **Memoire persistante** : faits stockes dans `jarvis_memoire.json` ET synchronises avec un vault Obsidian (`Jarvis/Memoire/*.md`, editables a la main)
- **Historique** : conversations sauvegardees + consultables dans le panneau chat (par jour)
- **Pont Claude Code bidirectionnel** : `/jarvis <message>` depuis Claude Code pour parler a Jarvis ; *"Jarvis demande a Claude Code..."* pour l'inverse
- **Surveillance d'inactivite Claude Code** : Jarvis te notifie si tu n'as pas relance Claude depuis X jours
- **Actions PC instantanees** (sans IA) : ouvrir Chrome / VSCode / Spotify / Obsidian / Google Maps / YouTube / etc., volume, capture, mute, copier/coller, taper du texte
- **Actions dev** : ouvrir un projet dans VSCode, git status / log du jour, terminal sur un dossier, timer/pomodoro, note rapide vers Obsidian, lecture du presse-papier
- **System tray Windows** : icone bleue dans la zone de notification, click pour ouvrir l'orbe
- **Raccourci global Ctrl+Shift+J** : ramene la fenetre Jarvis au premier plan depuis n'importe quelle app
- **Push-to-talk** : maintiens **Espace** dans la page web pour parler sans dire "Jarvis"
- **Input texte** : champ de saisie en bas de l'orbe pour taper en silence
- **Mute persistant** : un clic = mute, jusqu'au prochain clic
- **Mobile** : interface HTML separee servie sur `:8080`, utilise Web Speech API native du tel
- **Dashboard de configuration** : vraie app de config sur `http://localhost:5173/dashboard.html` (lien ⚙ sur l'orbe, ou menu tray "Configuration") — profil utilisateur (famille, adresse, habitudes injectes dans le cerveau), cles API (presentes/absentes, jamais affichees), memoire visualisee en graphe interactif, chat ecrit, connecteurs MCP, skills, et test "quel modele Ollama pour mon PC ?" (detection RAM/GPU + recommandations)
- **Fenetres d'affichage** : *"Jarvis, montre-moi..."* — Jarvis ouvre une carte HTML sombre (Windows/macOS/Linux) pour montrer listes, comparatifs, images, liens
- **Connecteurs MCP** : branche des serveurs Model Context Protocol (stdio) via le dashboard, leurs tools deviennent utilisables par l'agent
- **Skills** : depose un `.py` dans `jarvis_skills/` (template dans le README du dossier), Jarvis le charge tout seul — meme a cote du `.exe`

## Demarrage

```bash
# Installer les deps Python + frontend
python -m pip install -r requirements.txt
cd frontend && npm install && cd ..

# Lancer Ollama et un modele
ollama serve
ollama pull qwen2.5:7b

# Mode tray (recommande)
python scripts/jarvis_tray.py

# Ou mode desktop standalone (fenetre frameless)
python jarvis_desktop.py

# Ou backend brut (avec Vite auto-lance)
python main2.py
```

### macOS

Le fichier `requirements.txt` est un freeze Windows complet. Sur macOS, utilise
plutot le mode web/backend :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
brew install portaudio
python -m pip install -r requirements-macos.txt
cd frontend && npm install && cd ..
python main2.py
```

Notes :
- `jarvis_desktop.py` reste Windows-first : il depend de PyQt5 WebEngine et de
  `win32api/win32gui` pour la fenetre flottante.
- Sur macOS, l'interface fiable est `http://localhost:5173` via `main2.py` ou
  `jarvis_web.py`.
- Certaines actions systeme sont adaptees (`open`, Terminal, presse-papier,
  raccourcis Command), mais les automatisations vocales peuvent demander les
  permissions macOS Accessibilite, Microphone et Enregistrement de l'ecran.

Le backend ouvre 3 ports :
- `:8765` WebSocket (frontend ↔ backend)
- `:5173` Vite (frontend Three.js)
- `:8080` HTTP (interface mobile)

## Configuration

Copier `.env.example` vers `.env` et remplir les cles dont tu as besoin. **Aucune cle n'est obligatoire** : sans clef Gemini valide, Jarvis bascule automatiquement sur Ollama.

- **Nom d'utilisateur** : Jarvis t'appelle "Monsieur" par defaut. Definis `JARVIS_USER_NAME` dans `.env` pour qu'il utilise ton prenom.
- **Home Assistant** (optionnel) : les entites domotique (lumieres, capteurs, batteries...) sont declarees dans `jarvis_home_config.py`. Copie `jarvis_home_config_example.py` vers `jarvis_home_config.py` et remplace les `entity_id` par les tiens (ce fichier est ignore par git, il ne contient que TES entites). Sans ce fichier, Jarvis utilise les exemples generiques.

```bash
# Forcer le mode local meme avec une cle Gemini valide
FORCE_OLLAMA=1 python scripts/jarvis_tray.py
```

## Architecture

`main2.py` (~3000 lignes) est le point d'entree monolithique. Il orchestre :

1. **WebSocket** sur `:8765` — multiplexe les clients (web, mobile, tray)
2. **HTTP** sur `:8080` pour le frontend mobile
3. **Auto-launch Vite** sur `:5173`
4. **Boucle voix** : reconnaissance, wake-word, TTS
5. **Pipeline de commande** :
   - Resolution locale (math, francais, conversion, traduction)
   - Vision ecran (Gemini multimodal si dispo)
   - **Actions dev** (`dev_actions.py`) — projets, git, timer, notes
   - **Actions PC** (`pc_actions.py`) — applis, web shortcuts, volume, etc.
   - **Pont Claude Code** — `*"demande a Claude Code..."*`
   - **Streaming Ollama + TTS phrase par phrase**

Modules cles :
- `main2.py` — orchestration
- `obsidian_memory.py` — pont vault Obsidian
- `pc_actions.py` — actions Windows immediates
- `dev_actions.py` — productivite dev
- `claude_bridge.py` — pont avec Claude Code CLI
- `jarvis_notify.py` — utilitaire d'envoi WS
- `jarvis_tray.py` — icone system tray
- `jarvis_desktop.py` — fenetre frameless pywebview
- `frontend/src/main.ts` — WebSocket client + UI
- `frontend/src/orb.ts` — rendu Three.js
- `frontend/src/screen_capture.ts` — partage ecran via getDisplayMedia
- `mobile/app.js` — interface mobile (Web Speech API)

## Stack

- **Python 3.12** : websockets, edge-tts, pygame, speech_recognition, pyautogui, requests
- **Ollama** : qwen2.5:7b (chat), llama3.2:3b (rapide), deepseek-coder-v2:lite (code)
- **Frontend** : Vite + TypeScript + Three.js (sans framework UI)
- **Tray** : pystray + Pillow
- **Desktop** : pywebview (WebView2 sur Windows)
- **Hotkey global** : keyboard + pygetwindow

## Releases

Pousser un tag `vX.Y.Z` déclenche `.github/workflows/release.yml` : build du bundle frontend (fiable) + des binaires Windows (`Jarvis.exe`, `JarvisWeb.exe`) et macOS (mode web, best-effort), puis publication d'une release GitHub avec les artefacts. Bumper `VERSION` dans `jarvis_version.py` en même temps que le tag.

```bash
# Exemple
git tag v0.2.0 && git push origin v0.2.0
```

`jarvis_version.check_update()` interroge l'API GitHub pour signaler une version plus récente.

## Licence

Personnel, pas de licence ouverte pour le moment.
