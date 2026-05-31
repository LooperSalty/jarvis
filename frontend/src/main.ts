/**
 * J.A.R.V.I.S — Interface Web avec Orbe Three.js
 *
 * Se connecte au backend Python via WebSocket (ws://localhost:8765),
 * recoit les changements d'etat et pilote l'orbe en consequence.
 *
 * Etats: "idle" | "listening" | "thinking" | "speaking"
 */

import { createOrb, type OrbState } from "./orb";
import { injectVisionButton, captureFrame } from "./screen_capture";
import "./style.css";

// ── Config ────────────────────────────────────────────────────────────────────
const WS_URL = "ws://localhost:8765";
const RECONNECT_INTERVAL_MS = 2_000;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement;
const statusEl = document.getElementById("status-text") as HTMLDivElement;
const errorEl = document.getElementById("error-text") as HTMLDivElement;
const badgeEl = document.getElementById("connection-badge") as HTMLDivElement;
const badgeLabelEl = document.getElementById(
  "connection-label"
) as HTMLSpanElement;
const muteButtonEl = document.getElementById("mute-button") as HTMLButtonElement;
const textForm = document.getElementById("text-form") as HTMLFormElement;
const textInput = document.getElementById("text-input") as HTMLInputElement;
const pttButton = document.getElementById("ptt-button") as HTMLButtonElement;
const chatToggleEl = document.getElementById("chat-toggle") as HTMLButtonElement;
const chatPanelEl = document.getElementById("chat-panel") as HTMLElement;
const chatCloseEl = document.getElementById("chat-close") as HTMLButtonElement;
const chatMessagesEl = document.getElementById("chat-messages") as HTMLDivElement;
const chatArchiveBtn = document.getElementById("chat-archive") as HTMLButtonElement;
const chatArchiveListEl = document.getElementById("chat-archive-list") as HTMLDivElement;
const chatTitleEl = document.getElementById("chat-title") as HTMLSpanElement;

// ── Orb ───────────────────────────────────────────────────────────────────────
const orb = createOrb(canvas);

let muted = false;

// ── State labels (French) ────────────────────────────────────────────────────
const STATE_LABELS: Record<OrbState, string> = {
  idle: "",
  listening: "ecoute...",
  thinking: "reflexion...",
  speaking: "",
};

type PywebviewBridge = {
  api?: {
    show?: () => Promise<void> | void;
    hide?: () => Promise<void> | void;
    schedule_hide?: () => Promise<void> | void;
  };
};

function pywebview(): PywebviewBridge | undefined {
  return (globalThis as unknown as { pywebview?: PywebviewBridge }).pywebview;
}

function applyState(state: OrbState): void {
  if (muted && state !== "idle") {
    orb.setState("idle");
    statusEl.textContent = "";
    return;
  }
  orb.setState(state);
  statusEl.textContent = STATE_LABELS[state];

  const bridge = pywebview()?.api;
  if (bridge) {
    if (state !== "idle") {
      bridge.show?.();
    } else {
      bridge.schedule_hide?.();
    }
  }
}

function setMuted(muted: boolean): void {
  muteButtonEl.classList.toggle("is-muted", muted);
  muteButtonEl.setAttribute("aria-pressed", String(muted));
  muteButtonEl.textContent = muted ? "unmute" : "mute";
}

// ── Error toast ───────────────────────────────────────────────────────────────
let errorTimer: ReturnType<typeof setTimeout> | null = null;

function showError(msg: string): void {
  errorEl.textContent = msg;
  errorEl.style.opacity = "1";
  if (errorTimer) clearTimeout(errorTimer);
  errorTimer = setTimeout(() => {
    errorEl.style.opacity = "0";
  }, 4_000);
}

// ── Connection badge ──────────────────────────────────────────────────────────
function setConnected(ok: boolean): void {
  badgeEl.classList.toggle("connected", ok);
  badgeEl.classList.toggle("disconnected", !ok);
  badgeLabelEl.textContent = ok ? "connecte" : "reconnexion";
  muteButtonEl.disabled = !ok;
}

// ── WebSocket with auto-reconnect ─────────────────────────────────────────────
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    setConnected(true);
  });

  ws.addEventListener("message", async (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data as string) as {
        state?: string;
        action?: string;
        muted?: boolean;
        volume?: number;
        id?: string;
        role?: string;
        text?: string;
        ts?: string;
      };

      const dataAny = data as unknown as Record<string, unknown>;

      if (data.action === "chat_message" && typeof data.text === "string") {
        addChatMessage(data.role === "user" ? "user" : "jarvis", data.text, data.ts);
        return;
      }
      if (data.action === "history" && Array.isArray(dataAny.items)) {
        renderHistory(dataAny.items as Array<{ role: string; text: string }>);
        return;
      }
      if (data.action === "conversations_list" && Array.isArray(dataAny.days)) {
        renderConversationsList(dataAny.days as Array<{ date: string; size: number }>);
        return;
      }
      if (data.action === "conversation_content" && typeof dataAny.content === "string") {
        renderConversationContent(String(dataAny.date ?? ""), dataAny.content as string);
        return;
      }

      if (data.action === "request_screen_capture") {
        const frame = await captureFrame();
        if (frame && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "screen_frame",
            id: data.id,
            data: frame,
          }));
        } else if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "screen_frame",
            id: data.id,
            error: "no_stream",
          }));
        }
        return;
      }

      if (data.action === "demo") {
        orb.triggerDemo();
        return;
      }
      if (data.action === "set_volume" && typeof data.volume === "number") {
        orb.setVolume(data.volume);
        return;
      }
      if (data.state) {
        applyState(data.state as OrbState);
      }
      if (typeof data.volume === "number") {
        orb.setVolume(data.volume);
      }
      if (typeof data.muted === "boolean") {
        setMuted(data.muted);
      }
    } catch {
      // ignore malformed messages
    }
  });

  ws.addEventListener("close", () => {
    setConnected(false);
    applyState("idle");
    scheduleReconnect();
  });

  ws.addEventListener("error", () => {
    setConnected(false);
  });
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_INTERVAL_MS);
}

// ── Mute persistant (toggle local) ────────────────────────────────────────────
function applyMute(next: boolean): void {
  muted = next;
  setMuted(muted);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "set_mute", muted }));
    if (muted) {
      ws.send(JSON.stringify({ type: "stop_audio" }));
    }
  }
  if (muted) applyState("idle");
}

muteButtonEl.addEventListener("click", () => {
  applyMute(!muted);
});

// ── Chat panel ────────────────────────────────────────────────────────────────
function addChatMessage(role: "user" | "jarvis", text: string, ts?: string): void {
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  msg.textContent = text;
  if (ts) {
    const tsEl = document.createElement("span");
    tsEl.className = "ts";
    tsEl.textContent = ts;
    msg.appendChild(tsEl);
  }
  chatMessagesEl.appendChild(msg);
  while (chatMessagesEl.children.length > 200) {
    chatMessagesEl.removeChild(chatMessagesEl.firstChild!);
  }
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function clearChildren(el: HTMLElement): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function makeEmpty(text: string): HTMLDivElement {
  const d = document.createElement("div");
  d.className = "empty";
  d.textContent = text;
  return d;
}

function renderHistory(items: Array<{ role: string; text: string }>): void {
  clearChildren(chatMessagesEl);
  for (const it of items) {
    if (!it.text || it.text.startsWith("[Information retournée")) continue;
    addChatMessage(it.role === "user" ? "user" : "jarvis", it.text);
  }
}

let archiveOpen = false;

function showArchive(open: boolean): void {
  archiveOpen = open;
  chatArchiveBtn.classList.toggle("is-active", open);
  chatMessagesEl.classList.toggle("hidden", open);
  chatArchiveListEl.classList.toggle("hidden", !open);
  if (open && ws && ws.readyState === WebSocket.OPEN) {
    chatTitleEl.textContent = "Anciennes conversations";
    clearChildren(chatArchiveListEl);
    chatArchiveListEl.appendChild(makeEmpty("Chargement..."));
    ws.send(JSON.stringify({ type: "request_conversations" }));
  } else {
    chatTitleEl.textContent = "Conversation";
  }
}

function renderConversationsList(days: Array<{ date: string; size: number }>): void {
  if (!archiveOpen) return;
  clearChildren(chatArchiveListEl);
  if (days.length === 0) {
    chatArchiveListEl.appendChild(
      makeEmpty("Aucune conversation archivee. Active Obsidian pour persister."),
    );
    return;
  }
  for (const d of days) {
    const btn = document.createElement("button");
    btn.className = "day";
    btn.type = "button";
    const kb = (d.size / 1024).toFixed(1);
    const left = document.createElement("span");
    left.textContent = d.date;
    const right = document.createElement("span");
    right.className = "size";
    right.textContent = `${kb} ko`;
    btn.appendChild(left);
    btn.appendChild(right);
    btn.addEventListener("click", () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "request_conversation", date: d.date }));
      }
    });
    chatArchiveListEl.appendChild(btn);
  }
}

function renderConversationContent(date: string, content: string): void {
  if (!archiveOpen) return;
  clearChildren(chatArchiveListEl);
  const back = document.createElement("button");
  back.className = "back";
  back.type = "button";
  back.textContent = "Toutes les dates";
  back.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "request_conversations" }));
    }
  });
  chatArchiveListEl.appendChild(back);
  chatTitleEl.textContent = date || "Conversation";

  const stripped = content.replace(/^---[\s\S]*?---\n/m, "").trim();
  const div = document.createElement("div");
  div.className = "archive-content";
  div.textContent = stripped || "(vide)";
  chatArchiveListEl.appendChild(div);
}

chatToggleEl.addEventListener("click", () => {
  const willOpen = chatPanelEl.classList.contains("hidden");
  chatPanelEl.classList.toggle("hidden");
  if (willOpen && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "request_history", limit: 80 }));
  }
});
chatCloseEl.addEventListener("click", () => {
  chatPanelEl.classList.add("hidden");
  if (archiveOpen) showArchive(false);
});
chatArchiveBtn.addEventListener("click", () => {
  showArchive(!archiveOpen);
});

// ── Input texte ───────────────────────────────────────────────────────────────
textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const txt = textInput.value.trim();
  if (!txt || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "text_command", text: txt }));
  textInput.value = "";
});

// ── Push-to-talk (Web Speech API + bouton/Espace) ─────────────────────────────
type SpeechRecognitionLike = {
  start: () => void;
  stop: () => void;
  abort: () => void;
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

const SR: { new (): SpeechRecognitionLike } | undefined =
  (window as unknown as { SpeechRecognition?: { new (): SpeechRecognitionLike } }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: { new (): SpeechRecognitionLike } }).webkitSpeechRecognition;

let recognition: SpeechRecognitionLike | null = null;
let pttHolding = false;
let pttFinalText = "";

function startPTT(): void {
  if (pttHolding) return;
  if (!SR) {
    showError("Reconnaissance vocale indisponible (utilise Chrome ou Edge).");
    return;
  }
  pttHolding = true;
  pttFinalText = "";
  pttButton.classList.add("is-active");
  pttButton.setAttribute("aria-pressed", "true");

  recognition = new SR();
  recognition.lang = "fr-FR";
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.onresult = (ev) => {
    let final = "";
    for (let i = 0; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) final += r[0].transcript + " ";
    }
    if (final) pttFinalText = (pttFinalText + " " + final).trim();
  };
  recognition.onerror = (ev) => {
    if (ev.error !== "no-speech" && ev.error !== "aborted") {
      showError(`Voix: ${ev.error}`);
    }
  };
  recognition.onend = () => {
    pttButton.classList.remove("is-active");
    pttButton.setAttribute("aria-pressed", "false");
    pttHolding = false;
    if (pttFinalText && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "text_command", text: pttFinalText }));
    }
    pttFinalText = "";
    recognition = null;
  };
  try {
    recognition.start();
  } catch {
    /* ignore double-start */
  }
}

function stopPTT(): void {
  if (!pttHolding || !recognition) return;
  try {
    recognition.stop();
  } catch {
    /* noop */
  }
}

pttButton.addEventListener("mousedown", startPTT);
pttButton.addEventListener("mouseup", stopPTT);
pttButton.addEventListener("mouseleave", stopPTT);
pttButton.addEventListener("touchstart", (e) => { e.preventDefault(); startPTT(); }, { passive: false });
pttButton.addEventListener("touchend", (e) => { e.preventDefault(); stopPTT(); }, { passive: false });

window.addEventListener("keydown", (e) => {
  if (e.code !== "Space") return;
  if (document.activeElement === textInput) return;
  if (e.repeat) return;
  e.preventDefault();
  startPTT();
});
window.addEventListener("keyup", (e) => {
  if (e.code !== "Space") return;
  if (document.activeElement === textInput) return;
  stopPTT();
});

// ── Boot ──────────────────────────────────────────────────────────────────────
setConnected(false);
applyState("idle");
setMuted(false);
injectVisionButton();

// Mode "mini" : URL ?mini=1 → masque toute l'UI via CSS, garde l'orbe.
// jarvis_desktop.py charge la page avec ?mini=1 pour la mini-fenetre flottante,
// et bascule en mode complet en retirant la classe via window.evaluate_js().
if (new URLSearchParams(window.location.search).has("mini")) {
  document.body.classList.add("mini");
}

connect();

void showError;
