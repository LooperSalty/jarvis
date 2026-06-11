/**
 * Section "Vue d'ensemble" :
 * - statut de connexion backend
 * - nom d'utilisateur editable (dash_set_user_name)
 * - grille des integrations (pastilles vertes/grises)
 * - formulaire "definir une cle API" (dash_set_env) — les valeurs ne sont
 *   JAMAIS affichees, seulement presente/absente
 * - bandeau "redemarrage requis"
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  textInput,
  labeledField,
  button,
  statusDot,
  showToast,
  asString,
  asBool,
  asRecord,
} from "./sections";

const INTEGRATIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "gemini", label: "Gemini" },
  { id: "groq", label: "Groq" },
  { id: "grok", label: "Grok" },
  { id: "serpapi", label: "SerpAPI" },
  { id: "youtube", label: "YouTube" },
  { id: "home_assistant", label: "Home Assistant" },
  { id: "meross", label: "Meross" },
  { id: "obsidian", label: "Obsidian" },
  { id: "ollama", label: "Ollama" },
];

/** Liste blanche de repli si le backend ne renvoie pas env_keys. */
const ENV_KEYS_FALLBACK: readonly string[] = [
  "GEMINI_API_KEY",
  "GROQ_API_KEY",
  "XAI_API_KEY",
  "SERPAPI_API_KEY",
  "YOUTUBE_API_KEY",
  "HA_URL",
  "HA_TOKEN",
  "MEROSS_EMAIL",
  "MEROSS_PASSWORD",
];

function mount(root: HTMLElement): Cleanup {
  // ── Bandeau redemarrage ──
  const banner = el(
    "div",
    "banner-restart hidden",
    "Redemarrage de Jarvis requis pour appliquer les changements."
  );
  root.appendChild(banner);

  // ── Panneau backend + nom utilisateur ──
  const backend = panel("Backend", "Etat de la connexion et identite");
  const connRow = el("div", "overview-conn");
  let connDot = statusDot(
    ws.isConnected() ? "Backend connecte" : "Backend deconnecte",
    ws.isConnected()
  );
  connRow.appendChild(connDot);
  backend.body.appendChild(connRow);

  const nameInput = textInput("Monsieur", "");
  const nameBtn = button("Enregistrer", "primary");
  const nameRow = el("div", "form-row");
  nameRow.appendChild(labeledField("Nom d'utilisateur (Jarvis s'adresse a vous ainsi)", nameInput));
  nameRow.appendChild(nameBtn);
  backend.body.appendChild(nameRow);
  root.appendChild(backend.root);

  // ── Panneau integrations ──
  const integ = panel("Integrations", "Vert = configuree et active");
  const grid = el("div", "integration-grid");
  integ.body.appendChild(grid);
  root.appendChild(integ.root);

  // ── Panneau cles API ──
  const env = panel(
    "Cles API",
    "Les valeurs ne sont jamais affichees — seulement leur presence."
  );
  const envList = el("div", "env-list");
  env.body.appendChild(envList);

  const keySelect = el("select", "input") as HTMLSelectElement;
  const keyValue = el("input", "input") as HTMLInputElement;
  keyValue.type = "password";
  keyValue.placeholder = "Valeur de la cle";
  keyValue.autocomplete = "new-password";
  const keyBtn = button("Definir la cle", "primary");
  const keyForm = el("div", "form-row");
  keyForm.appendChild(labeledField("Cle", keySelect));
  keyForm.appendChild(labeledField("Valeur", keyValue));
  keyForm.appendChild(keyBtn);
  env.body.appendChild(keyForm);
  root.appendChild(env.root);

  // ── Rendu depuis dash_overview ──
  function renderIntegrations(flags: Record<string, unknown>): void {
    clearChildren(grid);
    for (const item of INTEGRATIONS) {
      grid.appendChild(statusDot(item.label, asBool(flags[item.id])));
    }
  }

  function renderEnvKeys(envKeys: Record<string, unknown>): void {
    const names = Object.keys(envKeys);
    const keys = names.length > 0 ? names : [...ENV_KEYS_FALLBACK];

    clearChildren(envList);
    for (const name of keys) {
      const row = el("div", "env-row");
      row.appendChild(el("code", "env-name", name));
      const present = asBool(envKeys[name]);
      row.appendChild(
        el(
          "span",
          `env-presence ${present ? "ok" : "missing"}`,
          present ? "presente ✓" : "absente"
        )
      );
      envList.appendChild(row);
    }

    const previous = keySelect.value;
    clearChildren(keySelect);
    for (const name of keys) {
      const opt = el("option", "", name) as HTMLOptionElement;
      opt.value = name;
      keySelect.appendChild(opt);
    }
    if (previous && keys.includes(previous)) keySelect.value = previous;
  }

  function renderOverview(msg: ws.WsMessage): void {
    nameInput.value = asString(msg.user_name, nameInput.value);
    renderIntegrations(asRecord(msg.integrations));
    renderEnvKeys(asRecord(msg.env_keys));
    banner.classList.toggle("hidden", !asBool(msg.restart_required));
  }

  function fetchOverview(): void {
    ws.send({ type: "dash_get_overview" });
  }

  // ── Actions utilisateur ──
  nameBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    if (!name) {
      showToast("Le nom ne peut pas etre vide.", false);
      return;
    }
    if (!ws.send({ type: "dash_set_user_name", name })) {
      showToast("Backend deconnecte.", false);
    }
  });

  keyBtn.addEventListener("click", () => {
    const key = keySelect.value;
    const value = keyValue.value.trim();
    if (!key || !value) {
      showToast("Choisis une cle et saisis une valeur.", false);
      return;
    }
    if (ws.send({ type: "dash_set_env", updates: { [key]: value } })) {
      keyValue.value = "";
    } else {
      showToast("Backend deconnecte.", false);
    }
  });

  // ── Abonnements WS ──
  const offOverview = ws.on("dash_overview", renderOverview);
  const offSaved = ws.on("dash_env_saved", (msg) => {
    if (asBool(msg.ok)) {
      showToast("Enregistre.");
      fetchOverview();
    } else {
      showToast(asString(msg.error, "Echec de l'enregistrement."), false);
    }
    if (asBool(msg.restart_required)) banner.classList.remove("hidden");
  });
  const offStatus = ws.onStatus((ok) => {
    // statusDot retourne un nouveau noeud : on remplace et on garde la reference
    const fresh = statusDot(ok ? "Backend connecte" : "Backend deconnecte", ok);
    connDot.replaceWith(fresh);
    connDot = fresh;
    if (ok) fetchOverview();
  });

  // Etat initial
  if (ws.isConnected()) fetchOverview();
  renderIntegrations({});
  renderEnvKeys({});

  return () => {
    offOverview();
    offSaved();
    offStatus();
  };
}

export const sectionOverview: Section = {
  id: "overview",
  label: "Vue d'ensemble",
  icon: "◉",
  mount,
};
