/**
 * Section "Memoire" :
 * - a gauche : graphe des souvenirs (canvas, rendu delegue a graph.ts)
 * - a droite : liste des souvenirs (cle, valeur, date) + ajout/suppression
 *
 * Protocole : dash_get_memory -> dash_memory {items, graph},
 * dash_memory_add / dash_memory_delete -> dash_memory_saved puis re-fetch.
 */

import { renderMemoryGraph } from "./graph";
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
  showToast,
  asString,
  asBool,
  asNumber,
  asArray,
  asRecord,
} from "./sections";

interface GraphNode {
  id: string;
  label: string;
  type: string;
  taille: number;
}

interface GraphLink {
  source: string;
  target: string;
}

interface MemoryItem {
  cle: string;
  valeur: string;
  timestamp: string;
}

interface SearchResult {
  cle: string;
  valeur: string;
  score: number;
}

function parseResults(raw: unknown): SearchResult[] {
  return asArray(raw).map((it) => {
    const r = asRecord(it);
    return {
      cle: asString(r.cle),
      valeur: asString(r.valeur),
      score: asNumber(r.score, 0),
    };
  });
}

/** Normalise la reponse serveur en donnees sures pour graph.ts. */
function parseGraph(raw: Record<string, unknown>): {
  nodes: GraphNode[];
  links: GraphLink[];
} {
  const nodes: GraphNode[] = asArray(raw.nodes).map((n) => {
    const r = asRecord(n);
    return {
      id: asString(r.id),
      label: asString(r.label),
      type: asString(r.type, "memoire"),
      taille: asNumber(r.taille, 1),
    };
  });
  const links: GraphLink[] = asArray(raw.links).map((l) => {
    const r = asRecord(l);
    return { source: asString(r.source), target: asString(r.target) };
  });
  return { nodes, links };
}

function parseItems(raw: unknown): MemoryItem[] {
  return asArray(raw).map((it) => {
    const r = asRecord(it);
    return {
      cle: asString(r.cle),
      valeur: asString(r.valeur),
      timestamp: asString(r.timestamp),
    };
  });
}

function mount(root: HTMLElement): Cleanup {
  const layout = el("div", "memory-layout");
  root.appendChild(layout);

  // ── Colonne gauche : graphe ──
  const pGraph = panel("Graphe de memoire", "Souvenirs et profil relies a Jarvis");
  pGraph.root.classList.add("memory-graph-panel");
  const canvas = el("canvas") as HTMLCanvasElement;
  canvas.id = "memory-graph";
  pGraph.body.appendChild(canvas);
  layout.appendChild(pGraph.root);

  // ── Colonne droite : liste + ajout ──
  const pList = panel("Souvenirs", "Memoire persistante de Jarvis");
  const listBox = el("div", "memory-list");
  pList.body.appendChild(listBox);

  const addKey = textInput("Cle (ex : voiture)");
  const addValue = textInput("Valeur (ex : Tesla Model 3)");
  const addBtn = button("Ajouter", "primary");
  const addForm = el("div", "form-row");
  addForm.appendChild(labeledField("Cle", addKey));
  addForm.appendChild(labeledField("Valeur", addValue));
  addForm.appendChild(addBtn);
  pList.body.appendChild(addForm);
  layout.appendChild(pList.root);

  // ── Recherche semantique (RAG) ──
  const pSearch = panel(
    "Rechercher dans la memoire",
    "Recherche semantique par sens (embeddings locaux Ollama)"
  );
  const searchInput = textInput("Ex : quel vehicule j'ai ?");
  const searchBtn = button("Rechercher", "primary");
  const searchForm = el("div", "form-row");
  searchForm.appendChild(labeledField("Requete", searchInput));
  searchForm.appendChild(searchBtn);
  pSearch.body.appendChild(searchForm);
  const searchNote = el("div", "memory-search-note");
  searchNote.style.display = "none";
  pSearch.body.appendChild(searchNote);
  const resultsBox = el("div", "memory-results");
  pSearch.body.appendChild(resultsBox);
  layout.appendChild(pSearch.root);

  // ── Graphe : handle de rendu, detruit avant chaque re-rendu ──
  let graphHandle: { destroy(): void } | null = null;

  function destroyGraph(): void {
    if (graphHandle) {
      try {
        graphHandle.destroy();
      } catch (err) {
        console.error("[MEMOIRE] destroy graphe en erreur", err);
      }
      graphHandle = null;
    }
  }

  function renderGraph(raw: Record<string, unknown>): void {
    destroyGraph();
    try {
      graphHandle = renderMemoryGraph(canvas, parseGraph(raw));
    } catch (err) {
      console.error("[MEMOIRE] rendu graphe en erreur", err);
    }
  }

  // ── Liste ──
  function renderItems(items: MemoryItem[]): void {
    clearChildren(listBox);
    if (items.length === 0) {
      listBox.appendChild(el("div", "empty", "Aucun souvenir pour le moment."));
      return;
    }
    for (const item of items) {
      const row = el("div", "memory-item");
      const main = el("div", "memory-item-main");
      main.appendChild(el("strong", "memory-key", item.cle));
      main.appendChild(el("span", "memory-value", item.valeur));
      if (item.timestamp) {
        main.appendChild(el("span", "memory-ts", item.timestamp));
      }
      row.appendChild(main);

      const del = button("✕", "danger");
      del.classList.add("btn-icon");
      del.title = `Oublier "${item.cle}"`;
      del.addEventListener("click", () => {
        if (!ws.send({ type: "dash_memory_delete", cle: item.cle })) {
          showToast("Backend deconnecte.", false);
        }
      });
      row.appendChild(del);
      listBox.appendChild(row);
    }
  }

  function fetchMemory(): void {
    ws.send({ type: "dash_get_memory" });
  }

  // ── Recherche semantique : rendu des resultats ──
  function setSearchNote(message: string): void {
    if (message) {
      searchNote.textContent = message;
      searchNote.style.display = "";
    } else {
      searchNote.textContent = "";
      searchNote.style.display = "none";
    }
  }

  function renderResults(
    query: string,
    results: SearchResult[],
    rag: boolean
  ): void {
    clearChildren(resultsBox);
    if (!rag) {
      setSearchNote(
        "Recherche semantique indisponible (Ollama + modele d'embeddings requis)."
      );
      return;
    }
    setSearchNote("");
    if (results.length === 0) {
      resultsBox.appendChild(
        el("div", "empty", `Aucun resultat pour "${query}".`)
      );
      return;
    }
    for (const res of results) {
      const row = el("div", "memory-result");
      const head = el("div", "memory-result-head");
      head.appendChild(el("strong", "memory-key", res.cle));
      const pct = Math.round(Math.max(0, Math.min(1, res.score)) * 100);
      head.appendChild(el("span", "memory-score", `${pct}%`));
      row.appendChild(head);
      row.appendChild(el("span", "memory-value", res.valeur));
      resultsBox.appendChild(row);
    }
  }

  function runSearch(): void {
    const query = searchInput.value.trim();
    if (!query) {
      showToast("Saisis une requete de recherche.", false);
      return;
    }
    if (ws.send({ type: "dash_memory_search", query })) {
      setSearchNote("Recherche en cours...");
    } else {
      showToast("Backend deconnecte.", false);
    }
  }

  searchBtn.addEventListener("click", runSearch);
  searchInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runSearch();
    }
  });

  addBtn.addEventListener("click", () => {
    const cle = addKey.value.trim();
    const valeur = addValue.value.trim();
    if (!cle || !valeur) {
      showToast("Cle et valeur sont obligatoires.", false);
      return;
    }
    if (ws.send({ type: "dash_memory_add", cle, valeur })) {
      addKey.value = "";
      addValue.value = "";
    } else {
      showToast("Backend deconnecte.", false);
    }
  });

  // ── Abonnements WS ──
  const offMemory = ws.on("dash_memory", (msg) => {
    renderItems(parseItems(msg.items));
    renderGraph(asRecord(msg.graph));
  });
  const offSaved = ws.on("dash_memory_saved", (msg) => {
    if (asBool(msg.ok)) {
      showToast("Memoire mise a jour.");
      fetchMemory();
    } else {
      showToast(asString(msg.error, "Echec de la mise a jour memoire."), false);
    }
  });
  const offResults = ws.on("dash_memory_results", (msg) => {
    renderResults(
      asString(msg.query),
      parseResults(msg.results),
      asBool(msg.rag)
    );
  });
  const offStatus = ws.onStatus((ok) => {
    if (ok) fetchMemory();
  });

  if (ws.isConnected()) fetchMemory();
  renderItems([]);

  return () => {
    offMemory();
    offSaved();
    offResults();
    offStatus();
    destroyGraph();
  };
}

export const sectionMemory: Section = {
  id: "memory",
  label: "Memoire",
  icon: "🧠",
  mount,
};
