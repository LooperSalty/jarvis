# Jarvis — shell Tauri (expérimental)

Shell desktop **Tauri v2** (Rust + WebView2) pour Jarvis, alternative au shell
PyQt5/QtWebEngine actuel (`jarvis_core/jarvis_desktop.py`). But : une **WebView
moderne** (Edge Chromium à jour, corrige les soucis CSS de QtWebEngine Chromium 83)
et moins de faux positifs antivirus.

## Principe

Tauri **ne remplace pas** le backend Python — tout le cœur de Jarvis (WebSocket,
voix, IA, actions PC, MCP, mémoire) reste dans `jarvis_core/main2.py`. Le shell
Tauri se contente de :

1. **lancer `main2.py` en sidecar** (avec `JARVIS_NO_BROWSER=1` : sert le frontend
   buildé sur `http://localhost:5173` + WS `:8765`, sans navigateur ni fenêtre Qt) ;
2. afficher ce frontend dans une **fenêtre WebView2** ;
3. tuer le backend à la fermeture de la fenêtre.

Voir `src-tauri/src/lib.rs` (logique sidecar) et `src-tauri/tauri.conf.json`
(fenêtre → `localhost:5173`).

## Lancer (dev)

```bash
# 1) builder le frontend Jarvis au moins une fois :  cd ../frontend && npx vite build
cd jarvis-tauri
npm run tauri dev      # build debug + lance la fenêtre
```

## ⚠️ Pin de dépendance brotli (important — `Cargo.lock`)

`brotli` 8.0.3 (tiré par Tauri pour la compression d'assets) **ne compilait pas** :
échec du trait `Allocator` pour `StandardAlloc` (36 erreurs). Ce **n'est pas** un
souci de version de Rust (build OK sur stable 1.95) mais un **skew de dépendance
transitive** :

- `brotli` 8.0.3 épingle `alloc-no-stdlib = "2.0"` (son trait `Allocator`) ;
- mais `alloc-stdlib` **0.2.3** a bumpé vers `alloc-no-stdlib` **3.0.0**, donc son
  `StandardAlloc` implémente le trait *v3* → incompatible avec le *v2* attendu par
  brotli.

**Correctif appliqué** (figé dans `Cargo.lock`) : rétrograder `alloc-stdlib` à
**0.2.2** (qui reste sur `alloc-no-stdlib` 2.0) :

```bash
cargo update -p alloc-stdlib --precise 0.2.2
```

Tout l'arbre utilise alors `alloc-no-stdlib` 2.0.4 et brotli compile. Garder ce pin
dans le `Cargo.lock` (ne pas faire `cargo update` global sans revérifier brotli).

## État : FONDATION (preuve de concept)

Fait : scaffold, config fenêtre, sidecar Python, kill propre, build qui passe.
Reste (migration complète, non fait) :
- **System tray** + mini-fenêtre orbe (équivalent `jarvis_desktop.py`).
- **Bundler un sidecar Python** pour la distribution (aujourd'hui le chemin du dépôt
  est en dur dans `lib.rs` : OK en dev, pas pour un installeur).
- **Pipeline de build/release** (compléter PyInstaller pour le shell).

> Note honnête (cf. discussion) : le gain de Tauri est marginal (WebView moderne,
> déjà contournée côté CSS) pour un coût élevé — comme le montre la galère de
> toolchain ci-dessus. Alternative bien moins chère si on veut juste virer
> Chromium 83 : passer le shell à **pywebview + WebView2** (100 % Python, zéro
> toolchain Rust).
