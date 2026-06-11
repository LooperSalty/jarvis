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
import "./dashboard.css";

const appRoot = document.getElementById("app");
if (!appRoot) {
  throw new Error("Element #app introuvable dans dashboard.html");
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
