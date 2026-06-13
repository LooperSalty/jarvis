/**
 * Theme & palettes partages entre la page orbe (main.ts) et le dashboard
 * (section Personnalisation). Source unique : aucune duplication des couleurs.
 *
 * Le backend (jarvis_ui_config.py) persiste { theme, accent, orb_style,
 * orb_color, cowork_folder }. Ici on traduit ces ids en couleurs concretes :
 * - theme/accent  -> variables CSS du dashboard (--accent & derives)
 * - orb_style/orb_color -> palette des 4 etats de l'orbe (Orb.setPalette)
 */

import type { OrbState, OrbShape } from "./orb";

export interface UiConfig {
  theme: string;
  accent: string;
  orb_style: string;
  orb_color: string;
  orb_shape: string;
  cowork_folder?: string;
}

export type OrbPaletteFull = Record<OrbState, string>;

/** Accent du dashboard par theme (doit rester en phase avec THEMES cote Python). */
export const THEME_ACCENTS: Record<string, string> = {
  cyan: "#4be1ff",
  violet: "#a86bff",
  emeraude: "#34e3a0",
  ambre: "#f1b24a",
  rose: "#ff6bcb",
  rouge: "#ff5a5a",
};

export const THEME_LABELS: Record<string, string> = {
  cyan: "Cyan",
  violet: "Violet",
  emeraude: "Émeraude",
  ambre: "Ambre",
  rose: "Rose",
  rouge: "Rouge",
  custom: "Personnalisé",
};

/** Fond [bg-0, bg-1] par theme : teinte sombre l'ambiance pour que chaque
 *  theme soit VISUELLEMENT distinct (pas juste l'accent). */
export const THEME_BG: Record<string, [string, string]> = {
  cyan: ["#04060c", "#0a101c"],
  violet: ["#07050e", "#130a1e"],
  emeraude: ["#040b08", "#0a1a14"],
  ambre: ["#0b0703", "#1a1208"],
  rose: ["#0b050c", "#190a16"],
  rouge: ["#0b0505", "#190a0a"],
};

/** Formes d'orbe disponibles (doivent rester en phase avec OrbShape + Python). */
export const ORB_SHAPES: OrbShape[] = ["galaxie", "oeil", "anneau"];

export const ORB_SHAPE_LABELS: Record<string, string> = {
  galaxie: "Galaxie",
  oeil: "Œil",
  anneau: "Anneau",
};

/** Palettes d'orbe pretes a l'emploi (4 couleurs par etat). */
export const ORB_PALETTES: Record<string, OrbPaletteFull> = {
  classique: { idle: "#4ca8e8", listening: "#6fd8ff", thinking: "#b066ff", speaking: "#66ffd1" },
  ironman: { idle: "#ff7a2d", listening: "#ffd24a", thinking: "#ff4d3d", speaking: "#ffae42" },
  nebuleuse: { idle: "#a86bff", listening: "#d49bff", thinking: "#ff6bcb", speaking: "#6f8bff" },
  emeraude: { idle: "#2ecc71", listening: "#7bffb0", thinking: "#34e3a0", speaking: "#c8ff7b" },
  givre: { idle: "#7fb8ff", listening: "#bfe6ff", thinking: "#9fd0ff", speaking: "#e8f6ff" },
};

export const ORB_LABELS: Record<string, string> = {
  classique: "Classique",
  ironman: "Iron Man",
  nebuleuse: "Nébuleuse",
  emeraude: "Émeraude",
  givre: "Givre",
  custom: "Personnalisé",
};

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

export function isHex(v: unknown): v is string {
  return typeof v === "string" && HEX_RE.test(v);
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Eclaircit (amount>0) ou assombrit (amount<0) une couleur "#rrggbb". */
function shade(hex: string, amount: number): string {
  const [r, g, b] = hexToRgb(hex);
  const adj = (c: number) =>
    amount >= 0 ? c + (255 - c) * amount : c * (1 + amount);
  return rgbToHex(adj(r), adj(g), adj(b));
}

/** Derive une palette d'orbe monochrome a partir d'une couleur de base. */
export function deriveOrbPalette(base: string): OrbPaletteFull {
  const b = isHex(base) ? base : ORB_PALETTES.classique.idle;
  return {
    idle: b,
    listening: shade(b, 0.28),
    thinking: shade(b, -0.18),
    speaking: shade(b, 0.45),
  };
}

/** Palette d'orbe effective pour une config (preset ou couleur personnalisee). */
export function resolveOrbPalette(cfg: Partial<UiConfig>): OrbPaletteFull {
  const style = cfg.orb_style || "classique";
  if (style === "custom") return deriveOrbPalette(cfg.orb_color || "");
  return ORB_PALETTES[style] || ORB_PALETTES.classique;
}

/** Accent effectif du dashboard pour une config (preset ou accent personnalise). */
export function resolveAccent(cfg: Partial<UiConfig>): string {
  if (cfg.theme === "custom" && isHex(cfg.accent)) return cfg.accent as string;
  return THEME_ACCENTS[cfg.theme || "cyan"] || THEME_ACCENTS.cyan;
}

/** Forme d'orbe effective pour une config (repli sur galaxie). */
export function resolveOrbShape(cfg: Partial<UiConfig>): OrbShape {
  const s = (cfg.orb_shape || "galaxie") as OrbShape;
  return ORB_SHAPES.includes(s) ? s : "galaxie";
}

/** Applique le theme du dashboard via les variables CSS (accent + fond). Chaque
 *  theme change l'accent ET la teinte du fond pour un rendu nettement distinct. */
export function applyDashboardTheme(cfg: Partial<UiConfig>): void {
  const accent = resolveAccent(cfg);
  const [r, g, b] = hexToRgb(accent);
  const root = document.documentElement.style;
  root.setProperty("--accent", accent);
  root.setProperty("--accent-dim", `rgba(${r}, ${g}, ${b}, 0.12)`);
  root.setProperty("--accent-border", `rgba(${r}, ${g}, ${b}, 0.45)`);
  root.setProperty("--panel-border", `rgba(${r}, ${g}, ${b}, 0.18)`);

  const theme = cfg.theme || "cyan";
  const [bg0, bg1] =
    theme !== "custom" && THEME_BG[theme]
      ? THEME_BG[theme]
      : [shade(accent, -0.95), shade(accent, -0.88)];
  root.setProperty("--bg-0", bg0);
  root.setProperty("--bg-1", bg1);
}

const LS_KEY = "jarvis_ui_config";

/** Cache localStorage : permet d'appliquer le theme INSTANTANEMENT au chargement
 *  (avant la reponse WS du backend), evitant un flash de couleur par defaut. */
export function lireConfigLocale(): Partial<UiConfig> | null {
  try {
    const brut = localStorage.getItem(LS_KEY);
    return brut ? (JSON.parse(brut) as Partial<UiConfig>) : null;
  } catch {
    return null;
  }
}

export function ecrireConfigLocale(cfg: Partial<UiConfig>): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(cfg));
  } catch {
    /* quota / mode prive : on ignore, le backend reste la source de verite */
  }
}
