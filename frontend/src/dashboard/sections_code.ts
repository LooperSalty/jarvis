/**
 * Section "Code" (onglet principal) : embarque l'Admin UI de free-claude-code
 * (proxy fcc-server : providers, modeles, messaging) dans une iframe, pour
 * configurer le modele de code local/gratuit (Qwen, DeepSeek) sans quitter Jarvis.
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
  let mode = ""; // "iframe" | "stopped" | "absent" — evite de recharger l'iframe

  function renderIframe(url: string): void {
    clearChildren(root);

    const bar = el("div", "");
    bar.style.display = "flex";
    bar.style.alignItems = "center";
    bar.style.marginBottom = "10px";
    const titre = el("strong", "", "Code — free-claude-code");
    const spacer = el("span", "");
    spacer.style.flex = "1";
    const reload = button("Recharger", "ghost");
    const openExt = button("Ouvrir dans le navigateur", "ghost");
    openExt.style.marginLeft = "8px"; // pas de flex-gap (QtWebEngine Chromium 83)
    bar.appendChild(titre);
    bar.appendChild(spacer);
    bar.appendChild(reload);
    bar.appendChild(openExt);
    root.appendChild(bar);

    const frame = el("iframe", "") as HTMLIFrameElement;
    frame.src = url;
    frame.setAttribute("title", "free-claude-code Admin");
    frame.style.width = "100%";
    frame.style.height = "78vh";
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
      "Code (free-claude-code)",
      "Configure et utilise un modele de code local/gratuit (Qwen, DeepSeek) pour Claude Code."
    );
    if (!installe) {
      p.body.appendChild(
        el(
          "p",
          "panel-note",
          "free-claude-code (fcc-server) n'est pas installe. Ouvre un terminal et tape `jarvis` une fois pour le lancer, ou installe-le."
        )
      );
      root.appendChild(p.root);
      return;
    }
    p.body.appendChild(
      el(
        "p",
        "panel-note",
        "Le proxy free-claude-code n'est pas demarre. Demarre-le pour afficher ici le panneau de configuration (providers, modele)."
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
      if (mode === "iframe") return; // deja affiche : ne pas recharger l'iframe
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
      // Le proxy met quelques secondes a etre pret : on re-verifie le statut.
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

export const sectionCode: Section = {
  id: "code",
  label: "Code",
  icon: "💻",
  mount,
};
