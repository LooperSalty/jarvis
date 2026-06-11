/**
 * Infrastructure commune des sections du dashboard.
 *
 * - Types Section / Cleanup
 * - Helpers DOM surs (textContent uniquement, jamais d'innerHTML
 *   avec des donnees serveur)
 * - Toast global de confirmation
 * - Registre SECTIONS consomme par main.ts
 *
 * Regle de securite : tout contenu provenant du backend passe par
 * textContent. innerHTML n'est utilise nulle part avec des donnees.
 */

import { sectionOverview } from "./sections_overview";
import { sectionProfile } from "./sections_profile";
import { sectionMemory } from "./sections_memory";
import { sectionChat } from "./sections_chat";
import { sectionConnectors } from "./sections_connectors";
import { sectionModel } from "./sections_model";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Fonction de nettoyage appelee quand on quitte une section. */
export type Cleanup = () => void;

export interface Section {
  id: string;
  label: string;
  /** Glyphe unicode affiche dans la sidebar (constante sure). */
  icon: string;
  mount: (root: HTMLElement) => Cleanup;
}

// ── Helpers DOM ───────────────────────────────────────────────────────────────

/** Cree un element avec classe et texte optionnels (texte via textContent). */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = "",
  text = ""
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

/** Vide tous les enfants d'un noeud. */
export function clearChildren(node: HTMLElement): void {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** Panneau standard avec titre, sous-titre optionnel et corps. */
export function panel(
  title: string,
  subtitle = ""
): { root: HTMLElement; body: HTMLElement } {
  const root = el("section", "panel");
  const head = el("header", "panel-head");
  head.appendChild(el("h2", "panel-title", title));
  if (subtitle) head.appendChild(el("p", "panel-subtitle", subtitle));
  root.appendChild(head);
  const body = el("div", "panel-body");
  root.appendChild(body);
  return { root, body };
}

/** Input texte standard. */
export function textInput(placeholder = "", value = ""): HTMLInputElement {
  const input = el("input", "input");
  input.type = "text";
  input.placeholder = placeholder;
  input.value = value;
  input.autocomplete = "off";
  input.spellcheck = false;
  return input;
}

/** Champ avec label au-dessus. */
export function labeledField(
  labelText: string,
  control: HTMLElement
): HTMLLabelElement {
  const wrap = el("label", "field");
  wrap.appendChild(el("span", "field-label", labelText));
  wrap.appendChild(control);
  return wrap;
}

/** Bouton avec variante visuelle. */
export function button(
  label: string,
  variant: "primary" | "ghost" | "danger" = "ghost"
): HTMLButtonElement {
  const btn = el("button", `btn btn-${variant}`, label);
  btn.type = "button";
  return btn;
}

/** Interrupteur on/off (checkbox stylisee). Retourne le wrapper et la checkbox. */
export function switchToggle(checked: boolean): {
  root: HTMLLabelElement;
  input: HTMLInputElement;
} {
  const root = el("label", "switch");
  const input = el("input");
  input.type = "checkbox";
  input.checked = checked;
  root.appendChild(input);
  root.appendChild(el("span", "switch-slider"));
  return { root, input };
}

/** Pastille d'etat verte/grise avec libelle. */
export function statusDot(label: string, on: boolean): HTMLElement {
  const wrap = el("div", `status-dot ${on ? "on" : "off"}`);
  wrap.appendChild(el("span", "dot"));
  wrap.appendChild(el("span", "dot-label", label));
  return wrap;
}

// ── Toast global ──────────────────────────────────────────────────────────────

let toastEl: HTMLDivElement | null = null;
let toastTimer: ReturnType<typeof setTimeout> | null = null;

/** Affiche un toast en bas de l'ecran (vert si ok, rouge sinon). */
export function showToast(message: string, ok = true): void {
  if (!toastEl) {
    toastEl = el("div", "toast");
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = message;
  toastEl.classList.toggle("err", !ok);
  toastEl.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl?.classList.remove("show");
  }, 3_000);
}

// ── Narrowing de donnees serveur (jamais de confiance aveugle) ───────────────

export function asString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

export function asBool(v: unknown): boolean {
  return v === true;
}

export function asNumber(v: unknown, fallback = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}

export function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

// ── Registre des sections ─────────────────────────────────────────────────────

export const SECTIONS: readonly Section[] = [
  sectionOverview,
  sectionProfile,
  sectionMemory,
  sectionChat,
  sectionConnectors,
  sectionModel,
];
