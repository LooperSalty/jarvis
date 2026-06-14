/**
 * Section "Cowork" : un CHAT AGENTIQUE ou Claude Code travaille pour toi dans un
 * dossier (specifique ou un dossier par defaut AUTO-CREE), avec choix du modele
 * (local, gratuit via le proxy) et du mode de permission (plan/auto/bypass).
 *
 * Chaque message -> dash_cowork_chat -> `claude --print` (--continue aux tours
 * suivants) dans le dossier. Claude Code edite des fichiers / lance des commandes.
 *
 * WS : dash_cowork_status / dash_set_cowork (dossier) ; dash_code_model (modeles) ;
 *   dash_cowork_chat {prompt, model, mode, continue} -> dash_cowork_reply {ok, text, folder}.
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  button,
  textInput,
  labeledField,
  showToast,
  asString,
  asArray,
} from "./sections";

function mount(root: HTMLElement): Cleanup {
  let busy = false;
  let started = false; // false = 1er message (nouvelle conv) ; true = --continue
  let selectedModel = "";

  root.style.display = "flex";
  root.style.flexDirection = "column";
  root.style.height = "84vh";

  // ── Barre dossier + options ──
  const bar = panel(
    "Cowork — Claude Code travaille pour toi",
    "Un chat ou Claude Code AGIT dans un dossier : il edite des fichiers et lance des commandes."
  );
  const folderInfo = el("p", "panel-note", "Dossier : …");
  bar.body.appendChild(folderInfo);

  const folderInput = textInput("C:\\chemin\\du\\projet (vide = dossier par defaut auto)", "");
  const setFolderBtn = button("Definir", "ghost");
  const defaultFolderBtn = button("Dossier par defaut (auto)", "ghost");
  const folderRow = el("div", "form-row");
  folderRow.appendChild(labeledField("Dossier de travail", folderInput));
  folderRow.appendChild(setFolderBtn);
  folderRow.appendChild(defaultFolderBtn);
  bar.body.appendChild(folderRow);

  const modelSelect = el("select", "input") as HTMLSelectElement;
  modelSelect.addEventListener("change", () => {
    selectedModel = modelSelect.value;
  });
  const modeSelect = el("select", "input") as HTMLSelectElement;
  for (const [v, t] of [
    ["default", "Demander les autorisations"],
    ["plan", "Plan (propose, n'execute pas)"],
    ["acceptEdits", "Automatique (accepte les editions)"],
    ["bypassPermissions", "Bypass (tout autoriser, prudence)"],
  ]) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = t;
    modeSelect.appendChild(o);
  }
  const optRow = el("div", "form-row");
  optRow.appendChild(labeledField("Modele (local)", modelSelect));
  optRow.appendChild(labeledField("Mode", modeSelect));
  bar.body.appendChild(optRow);
  root.appendChild(bar.root);

  // ── Messages ──
  const msgs = el("div", "");
  msgs.style.flex = "1";
  msgs.style.overflowY = "auto";
  msgs.style.padding = "8px";
  msgs.style.borderRadius = "12px";
  msgs.style.background = "rgba(255,255,255,0.03)";
  msgs.style.margin = "10px 0";
  root.appendChild(msgs);
  const intro = el(
    "p",
    "panel-note",
    "Decris une tache : Claude Code la realise dans le dossier (fichiers, commandes), via un modele local gratuit. « Nouvelle conversation » repart de zero."
  );
  msgs.appendChild(intro);

  // ── Saisie ──
  const inputRow = el("div", "");
  inputRow.style.display = "flex";
  inputRow.style.alignItems = "flex-end";
  const ta = el("textarea", "input") as HTMLTextAreaElement;
  ta.placeholder = "Decris la tache a realiser dans le dossier (Entree = envoyer)…";
  ta.rows = 2;
  ta.spellcheck = false;
  ta.style.flex = "1";
  ta.style.resize = "vertical";
  const newBtn = button("Nouvelle conversation", "ghost");
  newBtn.style.marginLeft = "8px";
  const sendBtn = button("Envoyer", "primary");
  sendBtn.style.marginLeft = "8px";
  inputRow.appendChild(ta);
  inputRow.appendChild(newBtn);
  inputRow.appendChild(sendBtn);
  root.appendChild(inputRow);

  function bulle(role: "user" | "assistant", contenu: string): HTMLElement {
    const b = el("div", "");
    b.style.margin = "8px 0";
    b.style.padding = "10px 12px";
    b.style.borderRadius = "10px";
    b.style.whiteSpace = "pre-wrap";
    b.style.wordBreak = "break-word";
    if (role === "user") {
      b.style.background = "rgba(120,140,255,0.15)";
      b.style.marginLeft = "12%";
    } else {
      b.style.background = "rgba(255,255,255,0.05)";
      b.style.marginRight = "8%";
      b.style.fontFamily = "ui-monospace, Menlo, Consolas, monospace";
      b.style.fontSize = "13px";
    }
    b.textContent = contenu;
    msgs.appendChild(b);
    msgs.scrollTop = msgs.scrollHeight;
    return b;
  }

  function envoyer(): void {
    const prompt = ta.value.trim();
    if (!prompt || busy) return;
    const mode = modeSelect.value;
    if (
      mode === "bypassPermissions" &&
      !window.confirm(
        "Mode Bypass : Claude Code executera toutes les actions sans te demander, " +
          "dans le dossier Cowork. Continuer ?"
      )
    ) {
      return;
    }
    bulle("user", prompt);
    ta.value = "";
    busy = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "…";
    const pend = bulle("assistant", "… Claude Code travaille dans le dossier (cela peut prendre un moment)…");
    pend.dataset.pending = "1";
    const ok = ws.send({ type: "dash_cowork_chat", prompt, model: selectedModel, mode, continue: started });
    if (ok) {
      started = true;
    } else {
      pend.textContent = "Backend deconnecte.";
      delete pend.dataset.pending;
      busy = false;
      sendBtn.disabled = false;
      sendBtn.textContent = "Envoyer";
    }
  }

  sendBtn.addEventListener("click", envoyer);
  ta.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      envoyer();
    }
  });
  newBtn.addEventListener("click", () => {
    started = false;
    clearChildren(msgs);
    msgs.appendChild(intro);
    showToast("Nouvelle conversation.");
  });
  setFolderBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_set_cowork", folder: folderInput.value.trim() })) {
      showToast("Backend deconnecte.", false);
    }
  });
  defaultFolderBtn.addEventListener("click", () => {
    folderInput.value = "";
    if (ws.send({ type: "dash_set_cowork", folder: "" })) {
      showToast("Dossier par defaut (auto-cree) au prochain message.");
    }
  });

  // ── Abonnements WS ──
  const offReply = ws.on("dash_cowork_reply", (msg) => {
    const texte = asString(msg.text, "(reponse vide)");
    const pend = msgs.querySelector('[data-pending="1"]') as HTMLElement | null;
    if (pend) {
      delete pend.dataset.pending;
      pend.textContent = texte;
    } else {
      bulle("assistant", texte);
    }
    const f = asString(msg.folder);
    if (f) folderInfo.textContent = `Dossier : ${f}`;
    busy = false;
    sendBtn.disabled = false;
    sendBtn.textContent = "Envoyer";
    msgs.scrollTop = msgs.scrollHeight;
  });
  const offStatus = ws.on("dash_cowork", (msg) => {
    const f = asString(msg.folder);
    if (f) {
      folderInfo.textContent = `Dossier : ${f}`;
      folderInput.value = f;
    } else {
      folderInfo.textContent = "Dossier : par defaut (auto-cree au 1er message)";
    }
  });
  const offModel = ws.on("dash_code_model", (msg) => {
    const actif = asString(msg.model);
    let modeles = asArray(msg.models).map((x) => asString(x)).filter(Boolean);
    if (!modeles.length && actif) modeles = [actif];
    clearChildren(modelSelect);
    if (!modeles.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "(defaut)";
      modelSelect.appendChild(o);
      selectedModel = "";
      return;
    }
    for (const nom of modeles) {
      const o = document.createElement("option");
      o.value = nom;
      o.textContent = nom;
      modelSelect.appendChild(o);
    }
    selectedModel = modeles.includes(actif) ? actif : modeles[0];
    modelSelect.value = selectedModel;
  });
  const offConn = ws.onStatus((ok) => {
    if (ok) {
      ws.send({ type: "dash_cowork_status" });
      ws.send({ type: "dash_code_model" });
    }
  });

  if (ws.isConnected()) {
    ws.send({ type: "dash_cowork_status" });
    ws.send({ type: "dash_code_model" });
  }

  return () => {
    offReply();
    offStatus();
    offModel();
    offConn();
  };
}

export const sectionCowork: Section = {
  id: "cowork",
  label: "Cowork",
  icon: "📂",
  mount,
};
