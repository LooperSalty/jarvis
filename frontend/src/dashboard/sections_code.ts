/**
 * Section "Code" (onglet principal) : un CHAT specialise programmation, branche
 * sur un modele LOCAL (Ollama : DeepSeek Coder / Qwen) — gratuit et prive, PAS
 * le Claude payant. La configuration (providers/modeles) est dans Parametres ->
 * Config Code (sections_code_config.ts).
 *
 * Protocole WS :
 *   -> dash_code_model            <- dash_code_model {model}
 *   -> dash_code_chat {prompt,history} <- dash_code_reply {ok, text}
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  button,
  asString,
  asBool,
  asArray,
} from "./sections";

interface Tour {
  role: "user" | "assistant";
  content: string;
}

function mount(root: HTMLElement): Cleanup {
  const history: Tour[] = [];
  let busy = false;
  let selectedModel = "";

  root.style.display = "flex";
  root.style.flexDirection = "column";
  root.style.height = "82vh";

  // ── En-tete (titre + selecteur de modele local + effacer) ──
  const header = el("div", "");
  header.style.display = "flex";
  header.style.alignItems = "center";
  header.style.marginBottom = "8px";
  const title = el("strong", "", "Assistant code");
  const lblModele = el("span", "panel-note", "modele local :");
  lblModele.style.margin = "0 8px";
  const modelSelect = el("select", "input") as HTMLSelectElement;
  modelSelect.style.maxWidth = "230px";
  modelSelect.addEventListener("change", () => {
    selectedModel = modelSelect.value;
  });
  const spacer = el("span", "");
  spacer.style.flex = "1";
  const clearBtn = button("Effacer", "ghost");
  header.appendChild(title);
  header.appendChild(lblModele);
  header.appendChild(modelSelect);
  header.appendChild(spacer);
  header.appendChild(clearBtn);
  root.appendChild(header);

  // ── Zone messages ──
  const msgs = el("div", "");
  msgs.style.flex = "1";
  msgs.style.overflowY = "auto";
  msgs.style.display = "flex";
  msgs.style.flexDirection = "column";
  msgs.style.padding = "14px 16px";
  msgs.style.borderRadius = "14px";
  msgs.style.background = "rgba(255,255,255,0.025)";
  msgs.style.marginBottom = "10px";
  root.appendChild(msgs);

  const intro = el(
    "p",
    "panel-note",
    "Pose une question de programmation : la reponse vient d'un modele LOCAL (gratuit, prive), pas de Claude. Le code est genere a cote, sans facturation."
  );
  msgs.appendChild(intro);

  // ── Saisie ──
  const inputRow = el("div", "");
  inputRow.style.display = "flex";
  inputRow.style.alignItems = "flex-end";
  const ta = el("textarea", "input") as HTMLTextAreaElement;
  ta.placeholder = "Decris ton besoin de code (Entree = envoyer, Maj+Entree = nouvelle ligne)…";
  ta.rows = 2;
  ta.spellcheck = false;
  ta.style.flex = "1";
  ta.style.resize = "vertical";
  const sendBtn = button("Envoyer", "primary");
  sendBtn.style.marginLeft = "8px";
  inputRow.appendChild(ta);
  inputRow.appendChild(sendBtn);
  root.appendChild(inputRow);

  function bulle(role: "user" | "assistant", contenu: string): HTMLElement {
    const estUser = role === "user";
    const wrap = el("div", "");
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.maxWidth = "84%";
    wrap.style.margin = "10px 0";
    wrap.style.alignSelf = estUser ? "flex-end" : "flex-start";

    const label = el("div", "", estUser ? "Toi" : "Assistant code");
    label.style.fontSize = "11px";
    label.style.opacity = "0.5";
    label.style.margin = estUser ? "0 4px 4px 0" : "0 0 4px 4px";
    label.style.alignSelf = estUser ? "flex-end" : "flex-start";

    const b = el("div", "");
    b.style.padding = "11px 14px";
    b.style.borderRadius = "14px";
    b.style.whiteSpace = "pre-wrap";
    b.style.wordBreak = "break-word";
    b.style.lineHeight = "1.5";
    if (estUser) {
      b.style.background = "rgba(75, 225, 255, 0.14)";
      b.style.borderBottomRightRadius = "5px";
    } else {
      b.style.background = "rgba(255, 255, 255, 0.05)";
      b.style.borderBottomLeftRadius = "5px";
      b.style.fontFamily = "ui-monospace, Menlo, Consolas, monospace";
      b.style.fontSize = "13px";
    }
    b.textContent = contenu;

    wrap.appendChild(label);
    wrap.appendChild(b);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
    return b;
  }

  function envoyer(): void {
    const prompt = ta.value.trim();
    if (!prompt || busy) return;
    bulle("user", prompt);
    ta.value = "";
    busy = true;
    sendBtn.disabled = true;
    sendBtn.textContent = "…";
    const pending = bulle("assistant", "… le modele local reflechit (le 1er appel charge le modele, ~30s)…");
    pending.dataset.pending = "1";
    const ok = ws.send({ type: "dash_code_chat", prompt, history: history.slice(), model: selectedModel });
    history.push({ role: "user", content: prompt });
    if (!ok) {
      pending.textContent = "Backend deconnecte.";
      delete pending.dataset.pending;
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
  clearBtn.addEventListener("click", () => {
    history.length = 0;
    clearChildren(msgs);
    msgs.appendChild(intro);
  });

  const offReply = ws.on("dash_code_reply", (msg) => {
    const texte = asString(msg.text, "(reponse vide)");
    const pend = msgs.querySelector('[data-pending="1"]') as HTMLElement | null;
    if (pend) {
      delete pend.dataset.pending;
      pend.textContent = texte;
    } else {
      bulle("assistant", texte);
    }
    if (asBool(msg.ok)) history.push({ role: "assistant", content: texte });
    busy = false;
    sendBtn.disabled = false;
    sendBtn.textContent = "Envoyer";
    msgs.scrollTop = msgs.scrollHeight;
  });

  const offModel = ws.on("dash_code_model", (msg) => {
    const actif = asString(msg.model);
    let modeles = asArray(msg.models).map((x) => asString(x)).filter(Boolean);
    if (!modeles.length && actif) modeles = [actif];
    const choix = selectedModel || actif;
    clearChildren(modelSelect);
    if (!modeles.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "aucun (lance Ollama)";
      modelSelect.appendChild(opt);
      selectedModel = "";
      return;
    }
    for (const nom of modeles) {
      const opt = document.createElement("option");
      opt.value = nom;
      opt.textContent = nom;
      modelSelect.appendChild(opt);
    }
    let valeur = modeles[0];
    if (modeles.includes(choix)) valeur = choix;
    else if (modeles.includes(actif)) valeur = actif;
    modelSelect.value = valeur;
    selectedModel = valeur;
  });

  const offConn = ws.onStatus((connecte) => {
    if (connecte) ws.send({ type: "dash_code_model" });
  });

  if (ws.isConnected()) ws.send({ type: "dash_code_model" });

  return () => {
    offReply();
    offModel();
    offConn();
  };
}

export const sectionCode: Section = {
  id: "code",
  label: "Code",
  icon: "💻",
  mount,
};
