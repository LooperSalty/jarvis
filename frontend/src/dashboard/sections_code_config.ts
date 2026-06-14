/**
 * Section "Config Code" (sous-onglet Parametres) : embarque l'Admin UI de
 * free-claude-code (proxy fcc-server : providers, modeles, messaging) en iframe.
 * Sert a configurer le routage de la commande `jarvis` (modele local Qwen/DeepSeek).
 * Le chat code lui-meme est dans l'onglet principal "Code" (sections_code.ts).
 *
 * Protocole WS :
 *   -> dash_fcc_status  <- dash_fcc_status {installe, en_marche, url_admin, port}
 *   -> dash_fcc_start   <- dash_fcc_started {ok, message}
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  button,
  showToast,
  asString,
  asBool,
} from "./sections";

function mount(root: HTMLElement): Cleanup {
  let pollTimer = 0;
  let mode = "";

  function renderIframe(url: string): void {
    clearChildren(root);
    const bar = el("div", "");
    bar.style.display = "flex";
    bar.style.alignItems = "center";
    bar.style.marginBottom = "10px";
    const titre = el("strong", "", "Configuration free-claude-code");
    const spacer = el("span", "");
    spacer.style.flex = "1";
    const reload = button("Recharger", "ghost");
    const openExt = button("Ouvrir dans le navigateur", "ghost");
    openExt.style.marginLeft = "8px";
    bar.appendChild(titre);
    bar.appendChild(spacer);
    bar.appendChild(reload);
    bar.appendChild(openExt);
    root.appendChild(bar);

    const frame = el("iframe", "") as HTMLIFrameElement;
    frame.src = url;
    frame.setAttribute("title", "free-claude-code Admin");
    frame.style.width = "100%";
    frame.style.height = "76vh";
    frame.style.border = "0";
    frame.style.borderRadius = "12px";
    frame.style.background = "#0b0b0f";
    root.appendChild(frame);

    reload.addEventListener("click", () => {
      frame.src = url;
    });
    openExt.addEventListener("click", () => {
      window.open(url, "_blank", "noopener");
    });
  }

  function renderStopped(installe: boolean): void {
    clearChildren(root);
    const p = panel(
      "Configuration du code (free-claude-code)",
      "Choisis le provider et le modele local/gratuit (Qwen, DeepSeek) utilises par la commande jarvis."
    );
    if (!installe) {
      p.body.appendChild(
        el(
          "p",
          "panel-note",
          "free-claude-code (fcc-server) n'est pas installe. Ouvre un terminal et tape `jarvis` une fois pour le lancer."
        )
      );
      root.appendChild(p.root);
      return;
    }
    p.body.appendChild(
      el(
        "p",
        "panel-note",
        "Le proxy n'est pas demarre. Demarre-le pour afficher la configuration (providers, modele)."
      )
    );
    const startBtn = button("Demarrer le proxy", "primary");
    startBtn.addEventListener("click", () => {
      startBtn.disabled = true;
      startBtn.textContent = "Demarrage...";
      if (!ws.send({ type: "dash_fcc_start" })) {
        showToast("Backend deconnecte.", false);
        startBtn.disabled = false;
        startBtn.textContent = "Demarrer le proxy";
      }
    });
    p.body.appendChild(startBtn);
    root.appendChild(p.root);
  }

  function render(msg: ws.WsMessage): void {
    if (asBool(msg.en_marche)) {
      if (pollTimer) {
        window.clearTimeout(pollTimer);
        pollTimer = 0;
      }
      if (mode === "iframe") return;
      mode = "iframe";
      renderIframe(asString(msg.url_admin) || "http://127.0.0.1:8082/admin");
    } else {
      const m = asBool(msg.installe) ? "stopped" : "absent";
      if (mode === m) return;
      mode = m;
      renderStopped(asBool(msg.installe));
    }
  }

  const offStatus = ws.on("dash_fcc_status", (msg) => render(msg));
  const offStarted = ws.on("dash_fcc_started", (msg) => {
    if (asBool(msg.ok)) {
      showToast(asString(msg.message, "Demarrage en cours..."));
      let tries = 0;
      const poll = (): void => {
        tries += 1;
        ws.send({ type: "dash_fcc_status" });
        if (tries < 8) pollTimer = window.setTimeout(poll, 2000);
      };
      pollTimer = window.setTimeout(poll, 2000);
    } else {
      showToast(asString(msg.message, "Echec du demarrage."), false);
    }
  });
  const offConn = ws.onStatus((ok) => {
    if (ok) ws.send({ type: "dash_fcc_status" });
  });

  if (ws.isConnected()) ws.send({ type: "dash_fcc_status" });

  return () => {
    offStatus();
    offStarted();
    offConn();
    if (pollTimer) window.clearTimeout(pollTimer);
  };
}

export const sectionCodeConfig: Section = {
  id: "code-config",
  label: "Config Code",
  icon: "⚙️",
  mount,
};
