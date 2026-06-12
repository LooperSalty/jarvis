# J.A.R.V.I.S — Personal local dev assistant

> 🇫🇷 **Version française : [README.md](README.md)**

A voice assistant that runs in the background on Windows, with a Three.js orb as its interface and a 100% local LLM (Ollama) as its brain. Built for a developer who wants to save time: quick project opening, git, notes, Claude Code integration, persistent memory synced with Obsidian.

## Installation (end user — Windows)

**No prerequisites**: no Python, no Node, no runtime needed. The graphical installer takes care of everything, even on a fresh Windows machine.

1. Download **`JarvisSetup-x.y.z.exe`** from the [latest release](https://github.com/LooperSalty/jarvis/releases/latest)
2. Run it and follow the wizard (available in English and French):
   - component selection: **Jarvis** (main app), **JarvisWeb** (browser mode), **ModelAdvisor** (which model fits my PC?)
   - **Local AI brain** (recommended): the installer downloads and installs **Ollama** automatically, then pulls the **model of your choice** (llama3.2:3b light / qwen2.5:7b quality / deepseek-coder-v2:lite code) — progress is shown live
   - options: desktop shortcut, start with Windows
3. That's it. Jarvis starts, the orb appears, and you configure the rest (optional API keys, profile, user name) in the built-in **dashboard** (tray menu → Configuration).

Notes:
- Installation is **per user** (`%LOCALAPPDATA%\Programs\Jarvis`), no admin rights needed. Jarvis stores its data (memory, profile, `.env`) **next to its `.exe`**: don't move it to a non-writable folder like `Program Files`.
- No network during installation? Jarvis installs anyway; you can install Ollama later from [ollama.com](https://ollama.com), then pull a model from the dashboard ("AI Model" section).
- Uninstalling (Control Panel → Jarvis) lets you keep or delete your data.
- Updates: the dashboard and the tray menu ("Check for updates") detect new GitHub releases.

## Features

- **Voice**: French speech recognition + edge-tts TTS (`fr-FR-HenriNeural` voice), "Jarvis" wake word
- **Local brain**: Ollama with `qwen2.5:7b` (fallbacks `llama3.2:3b`, `deepseek-coder-v2:lite`)
- **Sentence-by-sentence TTS streaming**: code blocks are not spoken (only shown in the chat panel)
- **3D orb**: ~9000 particles on animated Lissajous curves, reacts to state (idle / listening / thinking / speaking) and voice volume
- **Persistent memory**: facts stored in `jarvis_memoire.json` AND synced with an Obsidian vault (`Jarvis/Memoire/*.md`, hand-editable)
- **History**: conversations saved + browsable in the chat panel (by day)
- **Bidirectional Claude Code bridge**: `/jarvis <message>` from Claude Code to talk to Jarvis; *"Jarvis, ask Claude Code..."* for the other way around
- **Claude Code inactivity watch**: Jarvis notifies you if you haven't used Claude for X days
- **Instant PC actions** (no AI): open Chrome / VSCode / Spotify / Obsidian / Google Maps / YouTube / etc., volume, screenshot, mute, copy/paste, type text
- **Dev actions**: open a project in VSCode, git status / today's log, terminal in a folder, timer/pomodoro, quick note to Obsidian, clipboard reading
- **Windows system tray**: blue icon in the notification area, click to open the orb, built-in update check
- **Global hotkey Ctrl+Shift+J**: brings the Jarvis window to the front from any app
- **Push-to-talk**: hold **Space** in the web page to talk without saying "Jarvis"
- **Text input**: input field below the orb to type silently
- **Persistent mute**: one click = muted until the next click
- **Mobile**: separate HTML interface served on `:8080`, uses the phone's native Web Speech API
- **Configuration dashboard**: a real config app at `http://localhost:5173/dashboard.html` (⚙ link on the orb, or tray menu "Configuration") — user profile (family, address, habits injected into the brain), API keys (present/absent, never displayed), memory shown as an interactive graph, text chat, MCP connectors, skills, installed version + update link, and "which Ollama model for my PC?" (RAM/GPU detection + recommendations + one-click install)
- **Display windows**: *"Jarvis, show me..."* — Jarvis opens a dark HTML card (Windows/macOS/Linux) to show lists, comparisons, images, links
- **MCP connectors**: plug Model Context Protocol (stdio) servers via the dashboard, their tools become usable by the agent
- **OpenClaw bridge**: link Jarvis to your local [OpenClaw](https://docs.openclaw.ai) agent — *"ask openclaw to summarize my whatsapp messages"* (spoken answer), *"send to openclaw..."* (background task, reply on your messengers), *"openclaw status"*. Config: `OPENCLAW_TOKEN` / `OPENCLAW_HOOKS_TOKEN` in the dashboard
- **Skills**: drop a `.py` into `jarvis_skills/` (template in the folder's README), Jarvis loads it by itself — even next to the `.exe`

## Getting started (developer)

```bash
# Install Python + frontend deps
python -m pip install -r requirements-windows.txt   # curated Windows runtime set
cd frontend && npm install && cd ..

# Start Ollama and pull a model
ollama serve
ollama pull qwen2.5:7b

# Tray mode (recommended)
python scripts/jarvis_tray.py

# Or standalone desktop mode (frameless PyQt5 window)
python jarvis_desktop.py

# Or raw backend (auto-launches Vite)
python main2.py
```

> `requirements.txt` is a full freeze of the dev machine (conflicting pins):
> **do not use it on a clean env** — `requirements-windows.txt` is the curated list.

### Windows builds (.exe + installer)

```bash
# The 3 binaries (Jarvis.exe, JarvisWeb.exe, ModelAdvisor.exe) + copy to repo root
build_all.bat

# The JarvisSetup-x.y.z.exe installer (requires Inno Setup 6:
#   winget install JRSoftware.InnoSetup)
scripts\build_installer.bat
# → installer\output\JarvisSetup-<version>.exe
```

### macOS

`jarvis_desktop.py` is Windows-first (PyQt5 WebEngine + win32api). On macOS, use the web/backend mode:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
brew install portaudio
python -m pip install -r requirements-macos.txt
cd frontend && npm install && cd ..
python main2.py
```

Notes:
- On macOS the reliable interface is `http://localhost:5173` via `main2.py` or `jarvis_web.py`.
- Some system actions are adapted (`open`, Terminal, clipboard, Command shortcuts), but voice automations may require the macOS Accessibility, Microphone, and Screen Recording permissions.

The backend opens 3 ports:
- `:8765` WebSocket (frontend ↔ backend)
- `:5173` Vite (Three.js frontend)
- `:8080` HTTP (mobile interface)

### Docker (headless server mode)

To run Jarvis in a container (Linux server, NAS, VM…). A container has no mic, speaker, or display: the backend runs in **headless mode** (`JARVIS_HEADLESS=1`) and **STT/TTS happen in the browser** (Web Speech API) via the web or mobile UI. The local voice loop and pygame audio are disabled; everything else (Gemini/Groq/Grok/Ollama AI chain, dashboard, connectors, mobile) works.

```bash
# 1. Fill in API keys (at least GEMINI_API_KEY, or nothing for Ollama)
cp .env.example .env        # then edit .env

# 2a. Backend only (cloud brain)
docker compose up -d --build

# 2b. Or with embedded Ollama (100% local, "local" profile)
docker compose --profile local up -d --build
docker compose exec ollama ollama pull qwen2.5:7b   # first time: pull a model
```

Then open:
- **Orb + dashboard UI**: http://localhost:5173 (dashboard at `/dashboard.html`)
- **Mobile UI**: http://localhost:8080
- WebSocket: `ws://localhost:8765`

Without Compose:

```bash
docker build -t jarvis .
docker run -d --env-file .env -p 5173:5173 -p 8765:8765 -p 8080:8080 jarvis
```

Notes:
- The image uses **`requirements-docker.txt`** (minimal Linux set), **not** `requirements.txt`.
- Local mode: the `jarvis` service must point to the Ollama container — uncomment `OLLAMA_URL: "http://ollama:11434"` in `docker-compose.yml`.
- The code is frozen in the image: rebuild (`docker compose up -d --build`) after any change. Memory/profile persistence: see the commented binds in `docker-compose.yml`.

## Configuration

Copy `.env.example` to `.env` and fill in the keys you need — or do everything from the **dashboard** (Overview section), which writes the `.env` for you. **No key is mandatory**: without a valid Gemini key, Jarvis automatically falls back to Ollama.

- **User name**: Jarvis calls you "Monsieur" by default. Set `JARVIS_USER_NAME` (dashboard or `.env`) to make it use your first name.
- **Home Assistant** (optional): home automation entities (lights, sensors, batteries...) are declared in `jarvis_home_config.py`. Copy `jarvis_home_config_example.py` to `jarvis_home_config.py` and replace the `entity_id`s with yours (this file is gitignored, it only contains YOUR entities). Without it, Jarvis uses the generic examples.
- **Secrets**: sensitive keys go to the system vault (keyring) when available; the `.env` file gets an ACL restricted to your user account.

```bash
# Force local mode even with a valid Gemini key
FORCE_OLLAMA=1 python scripts/jarvis_tray.py
```

## Tests

**pytest** suite (`tests/`), run by CI on every PR:

```bash
python -m pytest
```

## Architecture

`main2.py` (~4300 lines) is the monolithic entry point. It orchestrates:

1. **WebSocket** on `:8765` — multiplexes clients (web, mobile, dashboard, tray)
2. **HTTP** on `:8080` for the mobile frontend
3. **Vite auto-launch** on `:5173`
4. **Voice loop**: recognition, wake word, TTS
5. **Command pipeline**:
   - Local resolution (math, French, conversion, translation)
   - Screen vision (Gemini multimodal when available)
   - **Dev actions** (`dev_actions.py`) — projects, git, timer, notes
   - **PC actions** (`pc_actions.py`) — apps, web shortcuts, volume, etc.
   - **Connectors** — Spotify, Meross, Playwright browser, OpenClaw, MCP
   - **Claude Code bridge** — *"ask Claude Code..."*
   - **Ollama streaming + sentence-by-sentence TTS**

Key modules:
- `main2.py` — orchestration
- `jarvis_dashboard_api.py` — WS router of the configuration dashboard
- `jarvis_version.py` — version + update check (GitHub releases)
- `jarvis_actions/` — PC/dev actions, connectors, local voice, routines, RAG
- `installer/JarvisSetup.iss` — Windows installer (Inno Setup)
- `frontend/src/main.ts` — WebSocket client + UI
- `frontend/src/orb.ts` — Three.js rendering
- `frontend/src/dashboard/` — configuration app
- `mobile/app.js` — mobile interface (Web Speech API)

## Stack

- **Python 3.12**: websockets, edge-tts, pygame, speech_recognition, pyautogui, google-genai
- **Ollama**: qwen2.5:7b (chat), llama3.2:3b (fast), deepseek-coder-v2:lite (code)
- **Frontend**: Vite + TypeScript + Three.js (no UI framework)
- **Desktop**: PyQt5 + QtWebEngine (frameless window + tray + mini-orb)
- **Global hotkey**: keyboard + pygetwindow
- **Packaging**: PyInstaller (.exe) + Inno Setup (installer)

## Releases

Pushing a `vX.Y.Z` tag triggers `.github/workflows/release.yml`: builds the frontend bundle, the Windows binaries (`Jarvis.exe`, `JarvisWeb.exe`, `ModelAdvisor.exe`), the **`JarvisSetup-x.y.z.exe` installer** (Inno Setup) and the macOS binary (web mode, best-effort), then publishes a GitHub release with the artifacts. Bump `VERSION` in `jarvis_version.py` (and `version_info.txt`) together with the tag.

```bash
# Example
git tag v0.2.0 && git push origin v0.2.0
```

`jarvis_version.check_update()` queries the GitHub API; the dashboard and the tray menu surface the new version.

## License

Personal project, no open license for now.
