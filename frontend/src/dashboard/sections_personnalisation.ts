/**
 * Section "Personnalisation" :
 * - Theme du dashboard (accent) : presets + couleur personnalisee.
 * - Couleur de Jarvis (l'orbe) : palettes presets + couleur personnalisee.
 *
 * Le theme du dashboard s'applique en LOCAL immediatement (variables CSS) ; la
 * couleur de l'orbe est poussee par le backend a la page orbe (action dash_ui)
 * pour un rendu live. Tout est persiste cote backend (jarvis_ui_config.json) et
 * mis en cache localStorage pour une application instantanee au rechargement.
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  showToast,
  asRecord,
  asString,
} from "./sections";
import {
  THEME_ACCENTS,
  THEME_LABELS,
  MODE_LABELS,
  ORB_PALETTES,
  ORB_LABELS,
  ORB_SHAPES,
  ORB_SHAPE_LABELS,
  applyDashboardTheme,
  resolveAccent,
  ecrireConfigLocale,
  isHex,
  type UiConfig,
} from "../ui_theme";

const MODE_IDS = ["auto", "clair", "sombre"];
const THEME_IDS = ["cyan", "violet", "emeraude", "ambre", "rose", "rouge"];
const ORB_IDS = ["classique", "ironman", "nebuleuse", "emeraude", "givre"];

// Apercu de pastille par mode : clair=blanc, sombre=noir, auto=les deux.
function apercuMode(id: string): string {
  if (id === "clair") return "#f4f6f8";
  if (id === "sombre") return "#10151f";
  return "linear-gradient(135deg, #f4f6f8 50%, #10151f 50%)";
}

function lireConfig(msg: ws.WsMessage): Partial<UiConfig> {
  const c = asRecord(msg.config);
  return {
    mode: asString(c.mode, "auto"),
    theme: asString(c.theme, "cyan"),
    accent: asString(c.accent, "#4be1ff"),
    orb_style: asString(c.orb_style, "classique"),
    orb_color: asString(c.orb_color, "#4ca8e8"),
    orb_shape: asString(c.orb_shape, "galaxie"),
    cowork_folder: asString(c.cowork_folder, ""),
  };
}

function mount(root: HTMLElement): Cleanup {
  let config: Partial<UiConfig> = {
    mode: "auto",
    theme: "cyan",
    accent: "#4be1ff",
    orb_style: "classique",
    orb_color: "#4ca8e8",
    orb_shape: "galaxie",
  };

  // ── Panneau mode d'apparence (clair / sombre / auto) ──
  const modePanel = panel(
    "Mode d'apparence",
    "Clair, sombre, ou detection automatique du theme de votre systeme."
  );
  const modeGrid = el("div", "swatch-grid");
  modePanel.body.appendChild(modeGrid);
  root.appendChild(modePanel.root);

  // ── Panneau theme du dashboard ──
  const themePanel = panel(
    "Theme du dashboard",
    "Couleur d'accent de cette interface de configuration."
  );
  const themeGrid = el("div", "swatch-grid");
  themePanel.body.appendChild(themeGrid);
  const accentInput = el("input", "color-input") as HTMLInputElement;
  accentInput.type = "color";
  const accentRow = el("label", "field color-field");
  accentRow.appendChild(el("span", "field-label", "Couleur personnalisee"));
  accentRow.appendChild(accentInput);
  themePanel.body.appendChild(accentRow);
  root.appendChild(themePanel.root);

  // ── Panneau orbe (forme + couleur) ──
  const orbPanel = panel(
    "Apparence de Jarvis (l'orbe)",
    "Forme et couleur de l'orbe — appliquees en direct sur l'interface principale."
  );
  orbPanel.body.appendChild(el("span", "field-label", "Forme de l'orbe"));
  const shapeGrid = el("div", "swatch-grid");
  orbPanel.body.appendChild(shapeGrid);
  orbPanel.body.appendChild(el("span", "field-label", "Couleur / palette"));
  const orbGrid = el("div", "swatch-grid");
  orbPanel.body.appendChild(orbGrid);
  const orbColorInput = el("input", "color-input") as HTMLInputElement;
  orbColorInput.type = "color";
  const orbColorRow = el("label", "field color-field");
  orbColorRow.appendChild(el("span", "field-label", "Couleur personnalisee"));
  orbColorRow.appendChild(orbColorInput);
  orbPanel.body.appendChild(orbColorRow);
  orbPanel.body.appendChild(
    el(
      "p",
      "panel-note",
      "Ouvre l'interface principale (l'orbe) pour voir le changement en direct."
    )
  );
  root.appendChild(orbPanel.root);

  function envoyer(updates: Partial<UiConfig>): void {
    if (!ws.send({ type: "dash_set_ui", updates })) {
      showToast("Backend deconnecte.", false);
    }
  }

  function appliquerLocal(): void {
    applyDashboardTheme(config);
    ecrireConfigLocale(config);
  }

  function choisirMode(id: string): void {
    config = { ...config, mode: id };
    appliquerLocal();
    renderModes();
    envoyer({ mode: id });
  }

  function choisirTheme(id: string): void {
    config = { ...config, theme: id };
    appliquerLocal();
    renderThemes();
    envoyer({ theme: id });
  }

  function choisirAccent(hex: string): void {
    if (!isHex(hex)) return;
    config = { ...config, theme: "custom", accent: hex };
    appliquerLocal();
    renderThemes();
    envoyer({ theme: "custom", accent: hex });
  }

  function choisirOrb(id: string): void {
    config = { ...config, orb_style: id };
    ecrireConfigLocale(config);
    renderOrbs();
    envoyer({ orb_style: id });
  }

  function choisirOrbColor(hex: string): void {
    if (!isHex(hex)) return;
    config = { ...config, orb_style: "custom", orb_color: hex };
    ecrireConfigLocale(config);
    renderOrbs();
    envoyer({ orb_style: "custom", orb_color: hex });
  }

  function choisirShape(id: string): void {
    config = { ...config, orb_shape: id };
    ecrireConfigLocale(config);
    renderShapes();
    envoyer({ orb_shape: id });
  }

  function renderShapes(): void {
    clearChildren(shapeGrid);
    for (const id of ORB_SHAPES) {
      const sw = el("button", "swatch") as HTMLButtonElement;
      sw.type = "button";
      sw.appendChild(el("span", `swatch-dot orb-shape orb-shape-${id}`));
      sw.appendChild(el("span", "swatch-label", ORB_SHAPE_LABELS[id] || id));
      if (config.orb_shape === id) sw.classList.add("active");
      sw.addEventListener("click", () => choisirShape(id));
      shapeGrid.appendChild(sw);
    }
  }

  function renderModes(): void {
    clearChildren(modeGrid);
    for (const id of MODE_IDS) {
      const sw = el("button", "swatch") as HTMLButtonElement;
      sw.type = "button";
      const dot = el("span", "swatch-dot");
      dot.style.background = apercuMode(id);
      dot.style.border = "1px solid rgba(128,128,128,0.4)";
      sw.appendChild(dot);
      sw.appendChild(el("span", "swatch-label", MODE_LABELS[id] || id));
      if ((config.mode || "auto") === id) sw.classList.add("active");
      sw.addEventListener("click", () => choisirMode(id));
      modeGrid.appendChild(sw);
    }
  }

  function renderThemes(): void {
    clearChildren(themeGrid);
    for (const id of THEME_IDS) {
      const sw = el("button", "swatch") as HTMLButtonElement;
      sw.type = "button";
      const dot = el("span", "swatch-dot");
      dot.style.background = THEME_ACCENTS[id];
      sw.appendChild(dot);
      sw.appendChild(el("span", "swatch-label", THEME_LABELS[id] || id));
      if (config.theme === id) sw.classList.add("active");
      sw.addEventListener("click", () => choisirTheme(id));
      themeGrid.appendChild(sw);
    }
    accentRow.classList.toggle("active", config.theme === "custom");
    accentInput.value = isHex(config.accent) ? (config.accent as string) : resolveAccent(config);
  }

  function renderOrbs(): void {
    clearChildren(orbGrid);
    for (const id of ORB_IDS) {
      const p = ORB_PALETTES[id];
      const sw = el("button", "swatch") as HTMLButtonElement;
      sw.type = "button";
      const dot = el("span", "swatch-dot orb");
      dot.style.background = `radial-gradient(circle at 35% 30%, ${p.listening}, ${p.idle} 55%, ${p.thinking})`;
      sw.appendChild(dot);
      sw.appendChild(el("span", "swatch-label", ORB_LABELS[id] || id));
      if (config.orb_style === id) sw.classList.add("active");
      sw.addEventListener("click", () => choisirOrb(id));
      orbGrid.appendChild(sw);
    }
    orbColorRow.classList.toggle("active", config.orb_style === "custom");
    orbColorInput.value = isHex(config.orb_color) ? (config.orb_color as string) : "#4ca8e8";
  }

  accentInput.addEventListener("change", () => choisirAccent(accentInput.value));
  orbColorInput.addEventListener("change", () => choisirOrbColor(orbColorInput.value));

  // ── Synchronisation backend ──
  const offUi = ws.on("dash_ui", (msg) => {
    if (asString(msg.error)) {
      showToast(asString(msg.error), false);
      return;
    }
    config = { ...config, ...lireConfig(msg) };
    appliquerLocal();
    renderModes();
    renderThemes();
    renderShapes();
    renderOrbs();
  });

  function fetchUi(): void {
    ws.send({ type: "dash_get_ui" });
  }

  const offStatus = ws.onStatus((ok) => {
    if (ok) fetchUi();
  });

  // Etat initial : rendu immediat (cache deja applique par main.ts) + fetch.
  renderModes();
  renderThemes();
  renderShapes();
  renderOrbs();
  if (ws.isConnected()) fetchUi();

  return () => {
    offUi();
    offStatus();
  };
}

export const sectionPersonnalisation: Section = {
  id: "personnalisation",
  label: "Personnalisation",
  icon: "🎨",
  mount,
};
