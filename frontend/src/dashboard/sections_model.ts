/**
 * Section "Modele IA" :
 * - "Analyser mon PC" -> dash_get_specs (cartes OS / CPU / RAM / GPU / VRAM)
 * - cases a cocher des usages (use_cases_disponibles, premier appel avec [])
 * - usages coches -> recommandation AUTO (dash_model_reco) sans clic
 * - "Recommander" -> dash_model_reco -> tableau (modele, taille, VRAM,
 *   score en barre, raison, badge installe)
 * - "Choisir ce modele" -> dash_model_select (definit le modele local prefere
 *   + lance ollama pull si absent)
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  button,
  showToast,
  asString,
  asBool,
  asNumber,
  asArray,
  asRecord,
} from "./sections";

interface ModelReco {
  name: string;
  tailleGb: number;
  vramGb: number;
  usages: string[];
  score: number;
  raison: string;
  installe: boolean;
  commandeInstall: string;
}

function parseModeles(raw: unknown): ModelReco[] {
  return asArray(raw).map((m) => {
    const r = asRecord(m);
    return {
      name: asString(r.name),
      tailleGb: asNumber(r.taille_gb),
      vramGb: asNumber(r.vram_necessaire_gb),
      usages: asArray(r.usages).map((u) => asString(u)),
      score: asNumber(r.score),
      raison: asString(r.raison),
      installe: asBool(r.installe),
      commandeInstall: asString(r.commande_install),
    };
  });
}

/** Normalise un score serveur (0..1 ou 0..100) en pourcentage 0..100. */
function scorePercent(score: number): number {
  const pct = score <= 1 ? score * 100 : score;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

function specCard(label: string, value: string): HTMLElement {
  const card = el("div", "spec-card");
  card.appendChild(el("span", "spec-label", label));
  card.appendChild(el("strong", "spec-value", value || "?"));
  return card;
}

function buildModelRow(model: ModelReco): HTMLTableRowElement {
  const tr = el("tr") as HTMLTableRowElement;

  const tdName = el("td");
  tdName.appendChild(el("strong", "", model.name));
  if (model.installe) tdName.appendChild(el("span", "badge-installed", "installe"));
  tr.appendChild(tdName);

  tr.appendChild(el("td", "", model.tailleGb ? `${model.tailleGb} Go` : "—"));
  tr.appendChild(el("td", "", model.vramGb ? `${model.vramGb} Go VRAM` : "—"));

  const tdScore = el("td", "td-score");
  const bar = el("div", "score-bar");
  const fill = el("div", "score-fill");
  fill.style.width = `${scorePercent(model.score)}%`;
  bar.appendChild(fill);
  tdScore.appendChild(bar);
  tdScore.appendChild(el("span", "score-num", `${scorePercent(model.score)}`));
  tr.appendChild(tdScore);

  tr.appendChild(el("td", "td-raison", model.raison));

  const tdActions = el("td");
  const chooseBtn = button(model.installe ? "Choisir ce modele" : "Installer & choisir", "primary");
  chooseBtn.title = model.installe
    ? `Definir ${model.name} comme modele local de Jarvis`
    : `Installer (${model.commandeInstall}) puis le definir comme modele local de Jarvis`;
  chooseBtn.addEventListener("click", () => {
    if (ws.send({ type: "dash_model_select", model: model.name })) {
      showToast(model.installe ? "Modele selectionne…" : "Installation lancee…");
    } else {
      showToast("Backend deconnecte.", false);
    }
  });
  tdActions.appendChild(chooseBtn);
  tr.appendChild(tdActions);
  return tr;
}

function mount(root: HTMLElement): Cleanup {
  // ── Panneau specs PC ──
  const pSpecs = panel("Mon PC", "Analyse du materiel pour dimensionner le modele");
  const analyseBtn = button("Analyser mon PC", "primary");
  pSpecs.body.appendChild(analyseBtn);
  const specsGrid = el("div", "specs-grid");
  pSpecs.body.appendChild(specsGrid);
  root.appendChild(pSpecs.root);

  // ── Panneau usages + recommandation ──
  const pReco = panel("Recommandation de modele", "Coche tes usages puis lance la recommandation");
  const usagesBox = el("div", "usages-grid");
  pReco.body.appendChild(usagesBox);
  const recoBtn = button("Recommander", "primary");
  pReco.body.appendChild(recoBtn);

  const tableWrap = el("div", "table-wrap");
  const table = el("table", "reco-table") as HTMLTableElement;
  const thead = el("thead");
  const headRow = el("tr");
  for (const h of ["Modele", "Taille", "VRAM requise", "Score", "Raison", ""]) {
    headRow.appendChild(el("th", "", h));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = el("tbody");
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  pReco.body.appendChild(tableWrap);
  root.appendChild(pReco.root);

  // ── Rendu specs ──
  function renderSpecs(specs: Record<string, unknown>): void {
    clearChildren(specsGrid);
    specsGrid.appendChild(specCard("OS", asString(specs.os)));
    specsGrid.appendChild(specCard("CPU", asString(specs.cpu)));
    const ram = asNumber(specs.ram_gb);
    specsGrid.appendChild(specCard("RAM", ram ? `${ram} Go` : ""));
    for (const rawGpu of asArray(specs.gpus)) {
      const gpu = asRecord(rawGpu);
      const vram = asNumber(gpu.vram_gb);
      specsGrid.appendChild(
        specCard("GPU", `${asString(gpu.name)}${vram ? ` (${vram} Go VRAM)` : ""}`)
      );
    }
    const vramMax = asNumber(specs.vram_max_gb);
    specsGrid.appendChild(specCard("VRAM max", vramMax ? `${vramMax} Go` : ""));
  }

  // ── Cases a cocher des usages (etat coche preserve entre rendus) ──
  function selectedUseCases(): string[] {
    return Array.from(
      usagesBox.querySelectorAll<HTMLInputElement>("input:checked")
    ).map((i) => i.value);
  }

  function renderUseCases(raw: unknown): void {
    const checked = new Set(selectedUseCases());
    clearChildren(usagesBox);
    for (const rawUc of asArray(raw)) {
      const uc = asRecord(rawUc);
      const id = asString(uc.id);
      if (!id) continue;
      const label = el("label", "usage-check");
      const input = el("input") as HTMLInputElement;
      input.type = "checkbox";
      input.value = id;
      input.checked = checked.has(id);
      // Recommandation immediate au cochage/decochage (plus besoin de cliquer
      // "Recommander" : la liste se met a jour des qu'on change un usage).
      input.addEventListener("change", lancerReco);
      label.appendChild(input);
      label.appendChild(el("span", "", asString(uc.label, id)));
      usagesBox.appendChild(label);
    }
    if (usagesBox.children.length === 0) {
      usagesBox.appendChild(el("div", "empty", "Usages indisponibles (backend deconnecte ?)."));
    }
  }

  function renderModeles(modeles: ModelReco[]): void {
    clearChildren(tbody);
    if (modeles.length === 0) {
      const tr = el("tr");
      const td = el("td", "empty", "Aucun resultat. Coche des usages puis clique Recommander.");
      td.colSpan = 6;
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const model of modeles) tbody.appendChild(buildModelRow(model));
  }

  // ── Actions ──
  function lancerReco(): void {
    if (!ws.send({ type: "dash_model_reco", use_cases: selectedUseCases() })) {
      showToast("Backend deconnecte.", false);
    }
  }

  analyseBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_get_specs" })) {
      showToast("Backend deconnecte.", false);
    }
  });
  recoBtn.addEventListener("click", lancerReco);

  // ── Abonnements WS ──
  const offSpecs = ws.on("dash_specs", (msg) => {
    renderSpecs(asRecord(msg.specs));
  });
  const offReco = ws.on("dash_model_reco", (msg) => {
    renderUseCases(msg.use_cases_disponibles);
    renderModeles(parseModeles(msg.modeles));
  });
  const offSelect = ws.on("dash_model_select", (msg) => {
    showToast(asString(msg.message) || "Modele mis a jour.", asBool(msg.ok));
    // Rafraichit la liste pour mettre a jour le badge "installe".
    lancerReco();
  });
  const offStatus = ws.onStatus((ok) => {
    // premier appel avec use_cases vide : recupere la liste des usages
    if (ok) ws.send({ type: "dash_model_reco", use_cases: [] });
  });

  if (ws.isConnected()) ws.send({ type: "dash_model_reco", use_cases: [] });
  renderUseCases([]);
  renderModeles([]);

  return () => {
    offSpecs();
    offReco();
    offSelect();
    offStatus();
  };
}

export const sectionModel: Section = {
  id: "model",
  label: "Modele IA",
  icon: "🧩",
  mount,
};
