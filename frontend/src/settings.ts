/**
 * Page Parametres + Tableau de bord.
 *
 * Panneau lateral (glisse depuis la gauche) avec deux onglets :
 *  - Tableau de bord : etat live du systeme (cerveau IA, integrations, memoire,
 *    interfaces connectees, son, mode Iron Man, reseau LAN).
 *  - Profil : informations personnelles que Jarvis utilise pour personnaliser
 *    ses reponses (famille, adresse, habitudes, gouts, instructions...).
 *    Persiste cote backend dans jarvis_profil.json.
 *
 * Dialogue WebSocket avec le backend :
 *   ->  get_status / get_profile / save_profile
 *   <-  status_data / profile_data / profile_saved
 *
 * Le meme frontend est servi en mode web (localhost:5173) et dans la
 * fenetre complete de l'app de bureau (jarvis_desktop.py), donc ce panneau
 * couvre les deux. Le hash d'URL (#parametres / #dashboard) permet d'ouvrir
 * directement un onglet (utilise par le menu du system tray).
 */

type WsGetter = () => WebSocket | null;

interface ProfilChamp {
  cle: string;
  label: string;
  hint: string;
  multiligne: boolean;
  valeur: string;
}
interface ProfilData {
  champs: ProfilChamp[];
  rempli: boolean;
}
interface StatusData {
  user_name: string;
  cerveau: string;
  gemini: boolean;
  force_ollama: boolean;
  clients: number;
  muted: boolean;
  iron_man: boolean;
  memoire_count: number;
  historique_count: number;
  profil_rempli: boolean;
  lan_ip: string;
  integrations: string[];
}

let getWs: WsGetter = () => null;

let toggleEl: HTMLButtonElement | null = null;
let panelEl: HTMLElement | null = null;
let closeEl: HTMLButtonElement | null = null;
let titleEl: HTMLElement | null = null;
let dashCardsEl: HTMLElement | null = null;
let profilFieldsEl: HTMLElement | null = null;
let saveEl: HTMLButtonElement | null = null;
let statusMsgEl: HTMLElement | null = null;
let tabButtons: HTMLButtonElement[] = [];
const tabPanes: Record<string, HTMLElement | null> = {};

const fieldInputs: Record<string, HTMLTextAreaElement | HTMLInputElement> = {};
let currentTab = "dashboard";

function send(obj: Record<string, unknown>): void {
  const ws = getWs();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function clear(el: HTMLElement): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function refresh(): void {
  send({ type: "get_status" });
  send({ type: "get_profile" });
}

function selectTab(tab: string): void {
  currentTab = tab;
  for (const btn of tabButtons) {
    btn.classList.toggle("is-active", btn.dataset.tab === tab);
  }
  for (const name of Object.keys(tabPanes)) {
    tabPanes[name]?.classList.toggle("is-active", name === tab);
  }
  if (titleEl) titleEl.textContent = tab === "profil" ? "Profil" : "Tableau de bord";
}

function isOpen(): boolean {
  return !!panelEl && !panelEl.classList.contains("hidden");
}

function openPanel(tab?: string): void {
  if (!panelEl) return;
  panelEl.classList.remove("hidden");
  selectTab(tab ?? currentTab);
  refresh();
}

function closePanel(): void {
  panelEl?.classList.add("hidden");
}

function card(label: string, value: string, tone?: "ok" | "bad" | "dim"): HTMLElement {
  const el = document.createElement("div");
  el.className = "dash-card" + (tone ? ` tone-${tone}` : "");
  const l = document.createElement("span");
  l.className = "dash-label";
  l.textContent = label;
  const v = document.createElement("span");
  v.className = "dash-value";
  v.textContent = value;
  el.appendChild(l);
  el.appendChild(v);
  return el;
}

function renderDashboard(s: StatusData): void {
  if (!dashCardsEl) return;
  clear(dashCardsEl);
  dashCardsEl.appendChild(card("Cerveau IA", s.cerveau));
  dashCardsEl.appendChild(card("Interfaces connectees", String(s.clients)));
  dashCardsEl.appendChild(card("Souvenirs", String(s.memoire_count)));
  dashCardsEl.appendChild(card("Messages echanges", String(s.historique_count)));
  dashCardsEl.appendChild(
    card("Profil", s.profil_rempli ? "Rempli" : "A completer", s.profil_rempli ? "ok" : "dim"),
  );
  dashCardsEl.appendChild(card("Son", s.muted ? "Coupe" : "Actif", s.muted ? "bad" : "ok"));
  dashCardsEl.appendChild(
    card("Mode Iron Man", s.iron_man ? "Actif" : "Inactif", s.iron_man ? "ok" : "dim"),
  );
  dashCardsEl.appendChild(
    card(
      "Integrations",
      s.integrations.length ? s.integrations.join(", ") : "Aucune",
      s.integrations.length ? undefined : "dim",
    ),
  );
  dashCardsEl.appendChild(card("Reseau (LAN)", s.lan_ip || "—"));
}

function renderProfile(p: ProfilData): void {
  if (!profilFieldsEl) return;
  clear(profilFieldsEl);
  for (const key of Object.keys(fieldInputs)) delete fieldInputs[key];
  for (const champ of p.champs) {
    const wrap = document.createElement("label");
    wrap.className = "profil-field";
    const lab = document.createElement("span");
    lab.className = "profil-label";
    lab.textContent = champ.label;
    wrap.appendChild(lab);
    let input: HTMLTextAreaElement | HTMLInputElement;
    if (champ.multiligne) {
      const ta = document.createElement("textarea");
      ta.rows = 2;
      input = ta;
    } else {
      const ip = document.createElement("input");
      ip.type = "text";
      input = ip;
    }
    input.value = champ.valeur || "";
    input.placeholder = champ.hint || "";
    wrap.appendChild(input);
    profilFieldsEl.appendChild(wrap);
    fieldInputs[champ.cle] = input;
  }
}

function collectProfile(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const cle of Object.keys(fieldInputs)) {
    out[cle] = fieldInputs[cle].value.trim();
  }
  return out;
}

function saveProfile(): void {
  send({ type: "save_profile", profile: collectProfile() });
  if (statusMsgEl) statusMsgEl.textContent = "Enregistrement...";
}

/** Consomme les messages WS relatifs aux parametres. Retourne true si traite. */
export function handleSettingsMessage(data: Record<string, unknown>): boolean {
  const action = data.action as string | undefined;
  if (action === "status_data") {
    renderDashboard(data.status as StatusData);
    return true;
  }
  if (action === "profile_data") {
    renderProfile(data.profile as ProfilData);
    return true;
  }
  if (action === "profile_saved") {
    if (statusMsgEl) {
      statusMsgEl.textContent = "Profil enregistre ✓";
      setTimeout(() => {
        if (statusMsgEl) statusMsgEl.textContent = "";
      }, 2500);
    }
    send({ type: "get_status" }); // profil_rempli a pu changer
    return true;
  }
  return false;
}

function applyHash(): void {
  const h = window.location.hash.replace("#", "").toLowerCase();
  if (h === "parametres" || h === "profil" || h === "settings") {
    openPanel("profil");
  } else if (h === "dashboard" || h === "tableau" || h === "tableau-de-bord") {
    openPanel("dashboard");
  }
}

export function initSettings(wsGetter: WsGetter): void {
  getWs = wsGetter;
  toggleEl = document.getElementById("settings-toggle") as HTMLButtonElement | null;
  panelEl = document.getElementById("settings-panel");
  closeEl = document.getElementById("settings-close") as HTMLButtonElement | null;
  titleEl = document.getElementById("settings-title");
  dashCardsEl = document.getElementById("dashboard-cards");
  profilFieldsEl = document.getElementById("profil-fields");
  saveEl = document.getElementById("profil-save") as HTMLButtonElement | null;
  statusMsgEl = document.getElementById("profil-status");

  if (!toggleEl || !panelEl) return;

  tabButtons = Array.from(panelEl.querySelectorAll<HTMLButtonElement>("#settings-tabs .tab"));
  tabPanes.dashboard = document.getElementById("tab-dashboard");
  tabPanes.profil = document.getElementById("tab-profil");

  for (const btn of tabButtons) {
    btn.addEventListener("click", () => selectTab(btn.dataset.tab || "dashboard"));
  }
  toggleEl.addEventListener("click", () => {
    if (isOpen()) closePanel();
    else openPanel();
  });
  closeEl?.addEventListener("click", closePanel);
  saveEl?.addEventListener("click", saveProfile);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen()) closePanel();
  });

  window.addEventListener("hashchange", applyHash);
  applyHash();
}
