/**
 * Jarvis — Dashboard de configuration.
 *
 * Page Vite separee (dashboard.html). Sidebar de navigation a gauche,
 * sections montees a la demande dans la zone de contenu. La connexion
 * WebSocket est partagee par toutes les sections via ./ws (singleton).
 */

import * as ws from "./ws";
import {
  SECTIONS,
  type Section,
  type Cleanup,
  el,
  clearChildren,
  showToast,
  asString,
} from "./sections";
import { applyDashboardTheme, lireConfigLocale } from "../ui_theme";
import "./dashboard.css";

// Applique le theme personnalise INSTANTANEMENT depuis le cache local (avant
// meme la connexion WS), pour eviter un flash de couleur par defaut. La section
// Personnalisation resynchronise ensuite depuis le backend (source de verite).
const _cfgLocale = lireConfigLocale();
if (_cfgLocale) applyDashboardTheme(_cfgLocale);

const appRoot = document.getElementById("app");
if (!appRoot) {
  throw new Error("Element #app introuvable dans dashboard.html");
}

// ── Repli flex-gap pour QtWebEngine (Chromium 83) ─────────────────────────────
// La fenetre native du configurateur (jarvis_desktop.py -> QWebEngineView, Qt
// 5.15.2 = Chromium 83) n'implemente PAS la propriete `gap` sur les conteneurs
// flex (seulement sur grid, OK depuis Chromium 66). Sans repli, tout l'espacement
// flex du dashboard s'effondre a 0 (pastilles collees au texte, formulaires
// serres). On detecte l'absence et on pose .no-flex-gap sur <html> : le CSS
// reproduit alors le gap par des marges equivalentes. Dans un navigateur moderne
// la classe n'est pas posee -> le `gap` natif est conserve (aucune regression).
function flexGapSupported(): boolean {
  const probe = document.createElement("div");
  probe.style.display = "flex";
  probe.style.flexDirection = "column";
  probe.style.gap = "1px";
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.appendChild(document.createElement("div"));
  probe.appendChild(document.createElement("div"));
  document.body.appendChild(probe);
  const supported = probe.scrollHeight === 1; // 2 enfants 0px + 1px de gap = 1
  probe.remove();
  return supported;
}
if (!flexGapSupported()) {
  document.documentElement.classList.add("no-flex-gap");
}

// ── Construction du layout ────────────────────────────────────────────────────

const sidebar = el("aside", "sidebar");

const brand = el("div", "brand");
brand.appendChild(el("span", "brand-title", "J.A.R.V.I.S"));
brand.appendChild(el("span", "brand-subtitle", "Configuration"));
sidebar.appendChild(brand);

const nav = el("nav", "nav");
sidebar.appendChild(nav);

const badge = el("div", "conn-badge disconnected");
badge.appendChild(el("span", "dot"));
badge.appendChild(el("span", "conn-label", "deconnecte"));
sidebar.appendChild(badge);

const content = el("main", "content");
const contentHead = el("header", "content-head");
const contentTitle = el("h1", "content-title", "");
contentHead.appendChild(contentTitle);
content.appendChild(contentHead);
const sectionRoot = el("div", "section-root");
content.appendChild(sectionRoot);

appRoot.appendChild(sidebar);
appRoot.appendChild(content);

// ── Navigation par sections (hash routing) ────────────────────────────────────

const navButtons = new Map<string, HTMLButtonElement>();
let activeCleanup: Cleanup | null = null;
let activeId = "";

function findSection(id: string): Section {
  return SECTIONS.find((s) => s.id === id) ?? SECTIONS[0];
}

function mountSection(id: string): void {
  const section = findSection(id);
  if (section.id === activeId) return;

  if (activeCleanup) {
    try {
      activeCleanup();
    } catch (err) {
      console.error("[DASHBOARD] cleanup de section en erreur", err);
    }
    activeCleanup = null;
  }

  clearChildren(sectionRoot);
  contentTitle.textContent = section.label;
  for (const [btnId, btn] of navButtons) {
    btn.classList.toggle("active", btnId === section.id);
  }

  activeId = section.id;
  try {
    activeCleanup = section.mount(sectionRoot);
  } catch (err) {
    console.error(`[DASHBOARD] montage de "${section.id}" en erreur`, err);
    clearChildren(sectionRoot);
    sectionRoot.appendChild(
      el("div", "empty err", "Erreur au chargement de cette section.")
    );
  }
}

for (const section of SECTIONS) {
  const btn = el("button", "nav-btn") as HTMLButtonElement;
  btn.type = "button";
  btn.appendChild(el("span", "nav-icon", section.icon));
  btn.appendChild(el("span", "nav-label", section.label));
  btn.addEventListener("click", () => {
    window.location.hash = section.id;
  });
  navButtons.set(section.id, btn);
  nav.appendChild(btn);
}

function sectionFromHash(): string {
  return window.location.hash.replace(/^#/, "") || SECTIONS[0].id;
}

window.addEventListener("hashchange", () => mountSection(sectionFromHash()));

// ── Badge de connexion ────────────────────────────────────────────────────────

const connLabel = badge.querySelector(".conn-label") as HTMLSpanElement;

ws.onStatus((ok) => {
  badge.classList.toggle("connected", ok);
  badge.classList.toggle("disconnected", !ok);
  connLabel.textContent = ok ? "connecte" : "reconnexion";
});

// ── Erreurs backend globales ──────────────────────────────────────────────────
// Le backend repond {action:"dash_error", error} pour un type inconnu ou une
// exception dans un handler. Sans cet abonnement, l'echec serait silencieux.
ws.on("dash_error", (msg) => {
  showToast(asString(msg.error, "Erreur de configuration."), false);
});

// ── Boot ──────────────────────────────────────────────────────────────────────

ws.connect();
mountSection(sectionFromHash());
