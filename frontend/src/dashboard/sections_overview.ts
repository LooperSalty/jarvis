/**
 * Section "Vue d'ensemble" :
 * - statut de connexion backend
 * - nom d'utilisateur editable (dash_set_user_name)
 * - grille des integrations (pastilles vertes/grises)
 * - formulaire "definir une cle API" (dash_set_env) — les valeurs ne sont
 *   JAMAIS affichees, seulement presente/absente
 * - appairage mobile : lien LAN + token (loopback uniquement, deja gate)
 * - securisation des cles vers le trousseau (keyring) si dispo
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

  // ── Panneau appairage mobile ──
  const pairing = panel(
    "Appairage mobile",
    "Connecte ton telephone (meme reseau Wi-Fi) en toute securite."
  );
  const showPairingBtn = button("Afficher le lien d'appairage", "primary");
  const regenPairingBtn = button("Regenerer", "danger");
  const pairingActions = el("div", "form-row");
  pairingActions.appendChild(showPairingBtn);
  pairingActions.appendChild(regenPairingBtn);
  pairing.body.appendChild(pairingActions);

  // Zone d'affichage du lien + token, remplie a la reception de dash_pairing.
  const pairingResult = el("div", "pairing-result hidden");
  pairing.body.appendChild(pairingResult);
  root.appendChild(pairing.root);

  // ── Panneau securisation des cles (keyring) ──
  const secrets = panel(
    "Securiser les cles",
    "Deplace les cles API du fichier .env vers le trousseau systeme."
  );
  const secretsNote = el("p", "panel-note", "");
  const migrateBtn = button("Deplacer les cles vers le trousseau (keyring)", "primary");
  secrets.body.appendChild(migrateBtn);
  secrets.body.appendChild(secretsNote);
  root.appendChild(secrets.root);

  /** Affiche le lien d'appairage + token recu (echappe via textContent). */
  function renderPairing(msg: ws.WsMessage): void {
    const token = asString(msg.token);
    const lanUrl = asString(msg.lan_url);
    const lanIp = asString(msg.lan_ip);

    clearChildren(pairingResult);
    pairingResult.classList.remove("hidden");

    pairingResult.appendChild(
      el(
        "p",
        "pairing-hint",
        "Ouvre ce lien sur ton telephone (meme reseau Wi-Fi) :"
      )
    );

    // Lien cliquable (href controle, texte via textContent) + bouton copier.
    const linkRow = el("div", "form-row");
    const link = el("a", "pairing-link", lanUrl || "(adresse LAN indisponible)");
    if (lanUrl) {
      link.href = lanUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    linkRow.appendChild(link);
    const copyLinkBtn = button("Copier le lien", "ghost");
    copyLinkBtn.addEventListener("click", () => {
      copierPressePapier(lanUrl, "Lien copie.");
    });
    linkRow.appendChild(copyLinkBtn);
    pairingResult.appendChild(linkRow);

    if (lanIp) {
      pairingResult.appendChild(
        el("p", "pairing-ip", `IP du PC sur le reseau : ${lanIp}`)
      );
    }

    // Token affiche en monospace (utile si saisie manuelle).
    const tokenRow = el("div", "form-row");
    tokenRow.appendChild(el("span", "field-label", "Token"));
    tokenRow.appendChild(el("code", "pairing-token", token || "(indisponible)"));
    const copyTokenBtn = button("Copier le token", "ghost");
    copyTokenBtn.addEventListener("click", () => {
      copierPressePapier(token, "Token copie.");
    });
    tokenRow.appendChild(copyTokenBtn);
    pairingResult.appendChild(tokenRow);
  }

  /** Copie une valeur dans le presse-papier avec retour visuel (toast). */
  function copierPressePapier(valeur: string, succes: string): void {
    if (!valeur) {
      showToast("Rien a copier.", false);
      return;
    }
    // En contexte non securise (http LAN), navigator.clipboard peut etre
    // absent a l'execution malgre le typage DOM : on verifie defensivement.
    const clip: Clipboard | undefined = navigator.clipboard;
    if (clip === undefined || typeof clip.writeText !== "function") {
      showToast("Copie automatique indisponible — selectionne le texte.", false);
      return;
    }
    clip.writeText(valeur).then(
      () => showToast(succes),
      () => showToast("Copie impossible.", false)
    );
  }

  /** Active/desactive le bloc keyring selon la disponibilite backend. */
  function renderKeyring(disponible: boolean): void {
    migrateBtn.disabled = !disponible;
    secretsNote.textContent = disponible
      ? "Les cles seront lues depuis le trousseau au prochain demarrage."
      : "Trousseau indisponible (pip install keyring).";
  }

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
    renderKeyring(asBool(msg.keyring));
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

  showPairingBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_get_pairing" })) {
      showToast("Backend deconnecte.", false);
    }
  });

  regenPairingBtn.addEventListener("click", () => {
    const ok = window.confirm(
      "Regenerer le token invalidera les appairages existants. Continuer ?"
    );
    if (!ok) return;
    if (!ws.send({ type: "dash_regen_pairing" })) {
      showToast("Backend deconnecte.", false);
    }
  });

  migrateBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_migrate_secrets" })) {
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
  const offPairing = ws.on("dash_pairing", renderPairing);
  const offMigrated = ws.on("dash_secrets_migrated", (msg) => {
    if (!asBool(msg.ok)) {
      showToast(asString(msg.error, "Migration des cles echouee."), false);
      return;
    }
    if (!asBool(msg.keyring)) {
      showToast("Trousseau indisponible — aucune cle deplacee.", false);
      return;
    }
    // Compte les cles effectivement migrees pour un retour parlant.
    const resultats = asRecord(msg.resultats);
    let migrees = 0;
    for (const nom of Object.keys(resultats)) {
      if (asBool(resultats[nom])) migrees += 1;
    }
    showToast(
      migrees > 0
        ? `${migrees} cle(s) deplacee(s) vers le trousseau.`
        : "Aucune cle a deplacer."
    );
    fetchOverview();
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
  renderKeyring(false);

  return () => {
    offOverview();
    offSaved();
    offPairing();
    offMigrated();
    offStatus();
  };
}

export const sectionOverview: Section = {
  id: "overview",
  label: "Vue d'ensemble",
  icon: "◉",
  mount,
};
