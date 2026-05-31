/**
 * J.A.R.V.I.S — Interface Mobile
 *
 * Se connecte au backend Python via WebSocket dynamiquement (même IP que le serveur HTTP).
 * Utilise Web Speech API pour STT (voix → texte) et SpeechSynthesis pour TTS (texte → voix).
 *
 * États: "idle" | "listening" | "thinking" | "speaking"
 */

// ── Config ─────────────────────────────────────────────────────────────────
const WS_URL = `ws://${window.location.hostname}:8765`;
const RECONNECT_DELAY_MS = 2500;
const SPEECH_LANG = "fr-FR";

// ── DOM Refs ────────────────────────────────────────────────────────────────
const badgeEl      = document.getElementById("connection-badge");
const badgeLabelEl = document.getElementById("connection-label");
const statusEl     = document.getElementById("status-text");
const userTextEl   = document.getElementById("user-text");
const jarvisTextEl = document.getElementById("jarvis-text");
const micBtn       = document.getElementById("mic-btn");
const micIcon      = micBtn.querySelector(".mic-icon");
const stopIcon     = micBtn.querySelector(".stop-icon");
const micLabelEl   = document.getElementById("mic-label");
const stopJarvisBtn= document.getElementById("stop-jarvis-btn");

// ── État de l'application ───────────────────────────────────────────────────
let currentState = "idle";
let ws           = null;
let isListening  = false;
let reconnectTimer = null;

// ── Gestion des états ───────────────────────────────────────────────────────
const STATE_LABELS = {
  idle:      "en attente",
  listening: "je vous écoute...",
  thinking:  "en réflexion...",
  speaking:  "jarvis répond...",
};

function applyState(state) {
  // Retirer l'ancien état du body
  document.body.classList.remove(
    "state-idle", "state-listening", "state-thinking", "state-speaking"
  );
  document.body.classList.add(`state-${state}`);
  currentState = state;
  statusEl.textContent = STATE_LABELS[state] || state;

  // Affichage du bouton Stop global seulement si ca parle
  if (state === "speaking") {
    stopJarvisBtn.style.display = "flex";
  } else {
    stopJarvisBtn.style.display = "none";
  }

  // Icône microphone
  if (state === "listening") {
    micIcon.style.display = "none";
    stopIcon.style.display = "block";
    micLabelEl.textContent = "APPUYER POUR ARRÊTER";
  } else {
    micIcon.style.display = "block";
    stopIcon.style.display = "none";
    micLabelEl.textContent = "APPUYER POUR PARLER";
  }
}

applyState("idle");

// Écouteur pour le bouton stop JARVIS
stopJarvisBtn.addEventListener("click", () => {
  window.speechSynthesis.cancel(); // Stoppe l'audio mobile
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop_audio" })); // Stoppe l'audio PC
  }
  applyState("idle");
});

// ── Badge de connexion ──────────────────────────────────────────────────────
function setConnected(ok) {
  badgeEl.classList.toggle("connected", ok);
  badgeEl.classList.toggle("disconnected", !ok);
  badgeLabelEl.textContent = ok ? "connecté" : "reconnexion...";
}
setConnected(false);

// ── WebSocket ───────────────────────────────────────────────────────────────
function connectWS() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }

  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    console.log("[WS] Connecté à", WS_URL);
    setConnected(true);
  });

  ws.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data);

      // État de l'orbe (envoyé par le backend lors de ses propres actions)
      if (data.state) {
        // On ignore les états "speaking" du PC si on gère nous-mêmes le TTS
        if (data.state !== "speaking") {
          applyState(data.state);
        }
      }

      // Réponse textuelle de JARVIS destinée au mobile
      if (data.action === "jarvis_response" && data.text) {
        afficherReponseJarvis(data.text);
        parleSynthese(data.text);
      }
    } catch (e) {
      console.error("[WS] Erreur parsing message :", e);
    }
  });

  ws.addEventListener("close", () => {
    console.log("[WS] Déconnecté. Reconnexion dans", RECONNECT_DELAY_MS, "ms...");
    setConnected(false);
    applyState("idle");
    scheduleReconnect();
  });

  ws.addEventListener("error", () => {
    setConnected(false);
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWS();
  }, RECONNECT_DELAY_MS);
}

function sendCommand(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn("[WS] WebSocket non connecté, commande ignorée.");
    return false;
  }
  ws.send(JSON.stringify({ type: "mobile_command", text }));
  return true;
}

// ── Affichage dialogue ──────────────────────────────────────────────────────
function afficherTexteUtilisateur(text) {
  userTextEl.textContent = `"${text}"`;
  jarvisTextEl.textContent = "";
}

function afficherReponseJarvis(text) {
  // Nettoyer les éventuels blocs JSON de la réponse pour l'affichage
  const textePropre = text
    .replace(/\{[^}]*\}/gs, "")        // supprimer blocs JSON
    .replace(/\s{2,}/g, " ")           // normaliser espaces
    .trim();
  jarvisTextEl.textContent = textePropre || text;
}

// ── TTS Web (Speech Synthesis) ──────────────────────────────────────────────
let synthVoice = null;

function chargerVoix() {
  const voices = window.speechSynthesis.getVoices();
  // Chercher une voix française de bonne qualité
  synthVoice =
    voices.find(v => v.lang === "fr-FR" && v.name.includes("Google")) ||
    voices.find(v => v.lang === "fr-FR") ||
    voices.find(v => v.lang.startsWith("fr")) ||
    null;
  console.log("[TTS] Voix sélectionnée :", synthVoice?.name || "par défaut");
}

window.speechSynthesis.addEventListener("voiceschanged", chargerVoix);
chargerVoix();

function parleSynthese(texte) {
  // Annuler toute synthèse en cours
  window.speechSynthesis.cancel();

  // Nettoyer le texte (enlever JSON pour ne lire que la partie conversationnelle)
  const textePropre = texte
    .replace(/\{[^}]*\}/gs, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  if (!textePropre) return;

  applyState("speaking");

  const utterance = new SpeechSynthesisUtterance(textePropre);
  utterance.lang = SPEECH_LANG;
  utterance.rate = 0.95;
  utterance.pitch = 0.9;
  utterance.volume = 1.0;

  if (synthVoice) {
    utterance.voice = synthVoice;
  }

  utterance.addEventListener("end", () => {
    applyState("idle");
  });

  utterance.addEventListener("error", (e) => {
    console.warn("[TTS] Erreur synthèse :", e.error);
    applyState("idle");
  });

  window.speechSynthesis.speak(utterance);
}

// ── STT Web Speech API ──────────────────────────────────────────────────────
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang           = SPEECH_LANG;
  recognition.continuous     = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.addEventListener("start", () => {
    isListening = true;
    applyState("listening");
    userTextEl.textContent  = "";
    jarvisTextEl.textContent = "";
    console.log("[STT] Écoute démarrée.");
  });

  recognition.addEventListener("result", (event) => {
    let interim   = "";
    let final_txt = "";

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        final_txt += transcript;
      } else {
        interim += transcript;
      }
    }

    // Affichage en temps réel des résultats intermédiaires
    userTextEl.textContent = `"${final_txt || interim}"`;

    if (final_txt) {
      console.log("[STT] Résultat final :", final_txt);
    }
  });

  recognition.addEventListener("end", () => {
    isListening = false;
    const texteCapture = userTextEl.textContent.replace(/^"|"$/g, "").trim();
    console.log("[STT] Fin écoute. Texte :", texteCapture);

    if (texteCapture) {
      applyState("thinking");
      const envoyé = sendCommand(texteCapture);
      if (!envoyé) {
        applyState("idle");
        userTextEl.textContent = "⚠ Non connecté à JARVIS";
      }
    } else {
      applyState("idle");
    }
  });

  recognition.addEventListener("error", (event) => {
    console.warn("[STT] Erreur :", event.error);
    isListening = false;
    applyState("idle");

    if (event.error === "not-allowed") {
      userTextEl.textContent =
        "⚠ Micro non autorisé. Activez le dans chrome://flags";
    } else if (event.error === "no-speech") {
      userTextEl.textContent = "";
    } else {
      userTextEl.textContent = `⚠ Erreur micro : ${event.error}`;
    }
  });

} else {
  // SpeechRecognition non supporté
  micBtn.disabled = true;
  statusEl.textContent = "micro non supporté sur ce navigateur";
  console.error("[STT] SpeechRecognition non disponible.");
}

// ── Bouton microphone ───────────────────────────────────────────────────────
micBtn.addEventListener("click", () => {
  if (!recognition) return;

  // Bloquer si JARVIS pense ou parle
  if (currentState === "thinking" || currentState === "speaking") return;

  if (isListening) {
    // Arrêter l'écoute
    recognition.stop();
  } else {
    // Annuler TTS en cours si nécessaire
    window.speechSynthesis.cancel();
    try {
      recognition.start();
    } catch (e) {
      console.warn("[STT] Impossible de démarrer :", e);
    }
  }
});

// ── Démarrage ───────────────────────────────────────────────────────────────
connectWS();
console.log("[JARVIS MOBILE] Interface initialisée. WebSocket :", WS_URL);
