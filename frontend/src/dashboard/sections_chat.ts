/**
 * Section "Chat" : conversation ecrite avec Jarvis.
 *
 * Reutilise le protocole EXISTANT de main2.py :
 * - envoi   {type: "text_command", text}
 * - reception {action: "chat_message", role, text, ts}
 *             {action: "jarvis_response", text}   (commandes mobiles : dedupe)
 *             {action: "set_state", state}        (thinking -> indicateur)
 * - historique {type: "request_history", limit: 80} -> {action: "history", items}
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  button,
  showToast,
  asString,
  asArray,
  asRecord,
} from "./sections";

const HISTORY_LIMIT = 80;
const MAX_MESSAGES = 200;
/** Fenetre de deduplication chat_message / jarvis_response (ms). */
const DEDUPE_WINDOW_MS = 5_000;

/** Normalise un texte pour la dedup (jarvis_response arrive sans markdown). */
function normalize(text: string): string {
  return text.replace(/[*#`]/g, "").replace(/\s+/g, " ").trim();
}

function mount(root: HTMLElement): Cleanup {
  const wrap = el("div", "chat-wrap");
  root.appendChild(wrap);

  const messagesBox = el("div", "chat-messages");
  wrap.appendChild(messagesBox);

  const typing = el("div", "chat-typing hidden", "Jarvis reflechit...");
  wrap.appendChild(typing);

  // Choix du mode de reponse : vocal (TTS local) ou texte seulement.
  // Persiste dans localStorage, envoye au backend a chaque message (flag vocal).
  const VOCAL_KEY = "jarvis_chat_vocal";
  let replyVocal = localStorage.getItem(VOCAL_KEY) !== "0";

  const form = el("form", "chat-form") as HTMLFormElement;
  const input = el("input", "input chat-input") as HTMLInputElement;
  input.type = "text";
  input.placeholder = "Ecris a Jarvis... (Entree pour envoyer)";
  input.autocomplete = "off";
  input.spellcheck = false;

  const vocalToggle = button("", "ghost") as HTMLButtonElement;
  vocalToggle.type = "button";
  vocalToggle.classList.add("chat-vocal-toggle");
  function refreshVocalToggle(): void {
    vocalToggle.textContent = replyVocal ? "🔊 Vocal" : "📝 Texte";
    vocalToggle.classList.toggle("is-text", !replyVocal);
    vocalToggle.title = replyVocal
      ? "Jarvis repond a voix haute. Clique pour passer en texte seulement."
      : "Jarvis repond en texte seulement. Clique pour reactiver la voix.";
  }
  vocalToggle.addEventListener("click", () => {
    replyVocal = !replyVocal;
    localStorage.setItem(VOCAL_KEY, replyVocal ? "1" : "0");
    refreshVocalToggle();
  });
  refreshVocalToggle();

  const sendBtn = button("Envoyer", "primary");
  sendBtn.type = "submit";
  form.appendChild(input);
  form.appendChild(vocalToggle);
  form.appendChild(sendBtn);
  wrap.appendChild(form);

  // Textes jarvis recents pour eviter le doublon chat_message + jarvis_response
  const recentJarvis: Array<{ text: string; t: number }> = [];

  function seenRecently(text: string): boolean {
    const now = Date.now();
    const norm = normalize(text);
    // purge des entrees trop vieilles
    while (recentJarvis.length > 0 && now - recentJarvis[0].t > DEDUPE_WINDOW_MS) {
      recentJarvis.shift();
    }
    return recentJarvis.some((r) => r.text === norm);
  }

  function rememberJarvis(text: string): void {
    recentJarvis.push({ text: normalize(text), t: Date.now() });
  }

  function appendMessage(role: "user" | "jarvis", text: string, ts = ""): void {
    messagesBox.querySelector(".empty")?.remove();
    const msg = el("div", `chat-msg ${role}`, text);
    if (ts) msg.appendChild(el("span", "chat-ts", ts));
    messagesBox.appendChild(msg);
    while (messagesBox.children.length > MAX_MESSAGES) {
      messagesBox.removeChild(messagesBox.firstChild as Node);
    }
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }

  function renderHistory(items: unknown): void {
    clearChildren(messagesBox);
    for (const raw of asArray(items)) {
      const it = asRecord(raw);
      const text = asString(it.text);
      if (!text || text.startsWith("[Information retournée")) continue;
      appendMessage(asString(it.role) === "user" ? "user" : "jarvis", text);
    }
    if (messagesBox.children.length === 0) {
      messagesBox.appendChild(
        el("div", "empty", "Aucun message. Dis bonjour a Jarvis !")
      );
    }
  }

  function fetchHistory(): void {
    ws.send({ type: "request_history", limit: HISTORY_LIMIT });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    if (!ws.send({ type: "text_command", text, vocal: replyVocal })) {
      showToast("Backend deconnecte.", false);
      return;
    }
    // Le backend re-broadcast le message user via chat_message :
    // on n'ajoute pas de bulle locale pour eviter le doublon.
    input.value = "";
  });

  // ── Abonnements WS ──
  const offChat = ws.on("chat_message", (msg) => {
    const text = asString(msg.text);
    if (!text) return;
    const role = asString(msg.role) === "user" ? "user" : "jarvis";
    if (role === "jarvis") {
      if (seenRecently(text)) return;
      rememberJarvis(text);
    }
    appendMessage(role, text, asString(msg.ts));
  });

  const offResponse = ws.on("jarvis_response", (msg) => {
    const text = asString(msg.text);
    if (!text || seenRecently(text)) return;
    rememberJarvis(text);
    appendMessage("jarvis", text);
  });

  const offState = ws.on("set_state", (msg) => {
    typing.classList.toggle("hidden", asString(msg.state) !== "thinking");
  });

  const offHistory = ws.on("history", (msg) => renderHistory(msg.items));

  const offStatus = ws.onStatus((ok) => {
    if (ok) fetchHistory();
  });

  if (ws.isConnected()) fetchHistory();
  input.focus();

  return () => {
    offChat();
    offResponse();
    offState();
    offHistory();
    offStatus();
  };
}

export const sectionChat: Section = {
  id: "chat",
  label: "Chat",
  icon: "💬",
  mount,
};
