// Visualisation de la memoire de Jarvis en graphe de force interactif.
// Rendu canvas 2D pilote par d3-force. Consomme par sections.ts via
// renderMemoryGraph(canvas, { nodes, links }).
//
// Langage visuel aligne sur l'orbe (orb.ts) : cyan lumineux sur fond bleu nuit.

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
} from "d3-force";
import type { SimulationLinkDatum, SimulationNodeDatum } from "d3-force";

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  taille: number;
}

export interface GraphLink {
  source: string;
  target: string;
}

/** Noeud interne enrichi par d3-force (x, y, vx, vy, fx, fy). */
interface SimNode extends SimulationNodeDatum, GraphNode {}

type SimLink = SimulationLinkDatum<SimNode>;

interface NodeStyle {
  couleur: string;
  rayon: number;
}

const STYLES_PAR_TYPE: Record<string, NodeStyle> = {
  hub: { couleur: "#4be1ff", rayon: 26 },
  categorie: { couleur: "#7fd4ff", rayon: 16 },
  memoire: { couleur: "#2e9fdf", rayon: 9 },
  profil: { couleur: "#9f7fff", rayon: 9 },
};
const STYLE_DEFAUT: NodeStyle = { couleur: "#2e9fdf", rayon: 9 };

const COULEUR_LIEN = "rgba(75,225,255,0.25)";
const COULEUR_LABEL = "#cfe9f5";
const POLICE_LABEL = "11px system-ui";
const LABEL_MAX_CHARS = 30;
const SEUIL_LABELS_PERMANENTS = 25;
const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3;
const PAS_ZOOM = 1.1;
const MARGE_HIT = 4;
const DPR_MAX = 2;

function styleDe(node: SimNode): NodeStyle {
  return STYLES_PAR_TYPE[node.type] ?? STYLE_DEFAUT;
}

function rayonDe(node: SimNode): number {
  // Le rayon en pixels vient du TYPE (hub 26 / categorie 16 / memoire-profil 9).
  // node.taille est un poids semantique (1..3) cote backend, pas un nombre de
  // pixels : on l'utilise comme leger multiplicateur borne autour du rayon du type.
  const base = styleDe(node).rayon;
  const t = node.taille;
  if (Number.isFinite(t) && t > 0) {
    const facteur = Math.min(1.4, Math.max(0.8, 0.8 + (t - 1) * 0.2));
    return base * facteur;
  }
  return base;
}

function tronquer(label: string): string {
  if (typeof label !== "string") return "";
  if (label.length <= LABEL_MAX_CHARS) return label;
  return label.slice(0, LABEL_MAX_CHARS - 1) + "…";
}

/**
 * Monte le graphe de force dans le canvas fourni.
 * Ne mute jamais les donnees d'entree (copies internes pour d3-force).
 * Retourne un handle avec destroy() pour tout demonter proprement.
 */
export function renderMemoryGraph(
  canvas: HTMLCanvasElement,
  graph: { nodes: GraphNode[]; links: GraphLink[] },
): { destroy(): void } {
  try {
    return creerGraphe(canvas, graph);
  } catch (e) {
    console.error("[GRAPH] Echec d'initialisation du graphe memoire:", e);
    return { destroy(): void {} };
  }
}

function creerGraphe(
  canvas: HTMLCanvasElement,
  graph: { nodes: GraphNode[]; links: GraphLink[] },
): { destroy(): void } {
  const ctxBrut = canvas.getContext("2d");
  if (!ctxBrut) {
    console.error("[GRAPH] Contexte 2D indisponible sur ce canvas");
    return { destroy(): void {} };
  }
  // Const non-nullable : le narrowing de ctxBrut ne survit pas aux closures.
  const ctx: CanvasRenderingContext2D = ctxBrut;

  // Copies internes : d3-force mute ses noeuds (x, y, vx, vy...),
  // on ne touche donc jamais aux objets passes par l'appelant.
  const noeudsEntree = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const liensEntree = Array.isArray(graph?.links) ? graph.links : [];
  const noeuds: SimNode[] = noeudsEntree.map((n) => ({ ...n }));
  const idsValides = new Set(noeuds.map((n) => n.id));
  const liens: SimLink[] = liensEntree
    .filter((l) => idsValides.has(l.source) && idsValides.has(l.target))
    .map((l) => ({ ...l }));
  if (liens.length !== liensEntree.length) {
    console.warn(
      `[GRAPH] ${liensEntree.length - liens.length} lien(s) ignore(s) (id de noeud inconnu)`,
    );
  }

  const labelsPermanents = noeuds.length < SEUIL_LABELS_PERMANENTS;

  // --- Etat de la vue (zoom + pan, en pixels CSS) ---
  let dpr = Math.min(window.devicePixelRatio || 1, DPR_MAX);
  let largeur = Math.max(1, canvas.clientWidth || canvas.parentElement?.clientWidth || 640);
  let hauteur = Math.max(1, canvas.clientHeight || canvas.parentElement?.clientHeight || 420);
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let survol: SimNode | null = null;
  let drag: SimNode | null = null;

  // Positions initiales : hub au centre, le reste en spirale autour
  // (evite le saut visuel du placement par defaut de d3 autour de l'origine).
  semerPositions();

  const forceCentre = forceCenter<SimNode>(largeur / 2, hauteur / 2);
  const simulation = forceSimulation<SimNode, SimLink>(noeuds)
    .force(
      "liens",
      forceLink<SimNode, SimLink>(liens)
        .id((n) => n.id)
        .distance((l) => {
          const s = l.source;
          const t = l.target;
          const rs = typeof s === "object" ? rayonDe(s) : STYLE_DEFAUT.rayon;
          const rt = typeof t === "object" ? rayonDe(t) : STYLE_DEFAUT.rayon;
          return rs + rt + 46;
        }),
    )
    .force("repulsion", forceManyBody<SimNode>().strength(-200).distanceMax(420))
    .force("centre", forceCentre)
    .force("collision", forceCollide<SimNode>().radius((n) => rayonDe(n) + 6).iterations(2))
    .on("tick", dessiner);
  // d3-force coupe son timer interne quand alpha < alphaMin : le rendu
  // s'arrete tout seul, et chaque interaction le relance (restart / dessiner).

  function semerPositions(): void {
    const angleOr = Math.PI * (3 - Math.sqrt(5));
    let i = 0;
    for (const n of noeuds) {
      if (n.type === "hub") {
        n.x = largeur / 2;
        n.y = hauteur / 2;
        continue;
      }
      const r = 60 + 13 * Math.sqrt(i);
      n.x = largeur / 2 + Math.cos(i * angleOr) * r;
      n.y = hauteur / 2 + Math.sin(i * angleOr) * r;
      i += 1;
    }
  }

  // --- Rendu ---

  function dessiner(): void {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr * zoom, 0, 0, dpr * zoom, dpr * panX, dpr * panY);
    dessinerLiens();
    dessinerNoeuds();
    dessinerLabels();
  }

  function dessinerLiens(): void {
    ctx.strokeStyle = COULEUR_LIEN;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const lien of liens) {
      const s = lien.source;
      const t = lien.target;
      if (typeof s !== "object" || typeof t !== "object") continue;
      ctx.moveTo(s.x ?? 0, s.y ?? 0);
      ctx.lineTo(t.x ?? 0, t.y ?? 0);
    }
    ctx.stroke();
  }

  function dessinerNoeuds(): void {
    for (const n of noeuds) {
      const st = styleDe(n);
      if (n.type === "hub") {
        // Glow leger sur le hub uniquement.
        ctx.shadowColor = st.couleur;
        ctx.shadowBlur = 22;
      } else if (n === survol) {
        ctx.shadowColor = st.couleur;
        ctx.shadowBlur = 10;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.fillStyle = st.couleur;
      ctx.beginPath();
      ctx.arc(n.x ?? 0, n.y ?? 0, rayonDe(n), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  function labelVisible(n: SimNode): boolean {
    if (n.type === "hub" || n.type === "categorie") return true;
    if (labelsPermanents) return true;
    return n === survol;
  }

  function dessinerLabels(): void {
    ctx.font = POLICE_LABEL;
    ctx.fillStyle = COULEUR_LABEL;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const n of noeuds) {
      if (!labelVisible(n)) continue;
      ctx.fillText(tronquer(n.label), n.x ?? 0, (n.y ?? 0) + rayonDe(n) + 4);
    }
  }

  // --- Conversion ecran -> monde et hit-test ---

  function versMonde(ev: { clientX: number; clientY: number }): { x: number; y: number } {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    return { x: (mx - panX) / zoom, y: (my - panY) / zoom };
  }

  function chercherNoeud(wx: number, wy: number): SimNode | null {
    let meilleur: SimNode | null = null;
    let meilleureDist = Infinity;
    for (const n of noeuds) {
      const d = Math.hypot((n.x ?? 0) - wx, (n.y ?? 0) - wy);
      if (d <= rayonDe(n) + MARGE_HIT && d < meilleureDist) {
        meilleur = n;
        meilleureDist = d;
      }
    }
    return meilleur;
  }

  // --- Interactions ---

  function onPointerDown(ev: PointerEvent): void {
    const { x, y } = versMonde(ev);
    const n = chercherNoeud(x, y);
    if (!n) return;
    drag = n;
    n.fx = x;
    n.fy = y;
    try {
      canvas.setPointerCapture(ev.pointerId);
    } catch {
      // setPointerCapture peut echouer (vieux navigateurs) : drag degrade mais fonctionnel
    }
    canvas.style.cursor = "grabbing";
    // Rechauffe la simulation pendant le drag (relance les ticks si endormie).
    simulation.alphaTarget(0.3).restart();
    ev.preventDefault();
  }

  function onPointerMove(ev: PointerEvent): void {
    const { x, y } = versMonde(ev);
    if (drag) {
      drag.fx = x;
      drag.fy = y;
      return; // le tick de la simulation redessine
    }
    const avant = survol;
    survol = chercherNoeud(x, y);
    canvas.style.cursor = survol ? "grab" : "default";
    // Redessine au survol meme quand la simulation dort.
    if (survol !== avant) dessiner();
  }

  function onPointerUp(ev: PointerEvent): void {
    if (!drag) return;
    drag.fx = null;
    drag.fy = null;
    drag = null;
    canvas.style.cursor = "default";
    simulation.alphaTarget(0); // laisse la simulation se rendormir
    try {
      canvas.releasePointerCapture(ev.pointerId);
    } catch {
      // capture deja relachee : sans consequence
    }
  }

  function onPointerLeave(): void {
    if (drag || !survol) return;
    survol = null;
    canvas.style.cursor = "default";
    dessiner();
  }

  function onWheel(ev: WheelEvent): void {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const facteur = ev.deltaY < 0 ? PAS_ZOOM : 1 / PAS_ZOOM;
    const nouveau = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom * facteur));
    if (nouveau === zoom) return;
    // Zoom centre sur le curseur : le point sous la souris reste fixe.
    panX = mx - ((mx - panX) / zoom) * nouveau;
    panY = my - ((my - panY) / zoom) * nouveau;
    zoom = nouveau;
    dessiner();
  }

  function onDblClick(): void {
    zoom = 1;
    panX = 0;
    panY = 0;
    // Petit coup de chaud pour que forceCenter recentre aussi les noeuds.
    simulation.alpha(0.3).restart();
    dessiner();
  }

  // --- Responsive (observer sur le parent, devicePixelRatio gere) ---

  function surRedimension(): void {
    try {
      // On mesure le CANVAS lui-meme (taille pilotee par le CSS :
      // #memory-graph { width:100%; height:420px }) et on ne touche QU'AU buffer
      // (canvas.width/height). Ecrire canvas.style.height ici creerait une boucle
      // de feedback avec un parent en hauteur auto + padding (le panneau s'etirerait
      // a l'infini). On ne pilote donc jamais la taille CSS depuis ici.
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      dpr = Math.min(window.devicePixelRatio || 1, DPR_MAX);
      largeur = w;
      hauteur = h;
      const bw = Math.round(w * dpr);
      const bh = Math.round(h * dpr);
      if (canvas.width !== bw) canvas.width = bw;
      if (canvas.height !== bh) canvas.height = bh;
      forceCentre.x(w / 2).y(h / 2);
      simulation.alpha(0.3).restart(); // relance le rendu apres resize
    } catch (e) {
      console.error("[GRAPH] Erreur de redimensionnement:", e);
    }
  }

  canvas.style.touchAction = "none"; // necessaire pour drag tactile via pointer events
  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointercancel", onPointerUp);
  canvas.addEventListener("pointerleave", onPointerLeave);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("dblclick", onDblClick);

  let observer: ResizeObserver | null = null;
  if (typeof ResizeObserver !== "undefined" && canvas.parentElement) {
    observer = new ResizeObserver(surRedimension);
    observer.observe(canvas.parentElement);
  } else {
    // Repli si pas de parent ou pas de ResizeObserver.
    window.addEventListener("resize", surRedimension);
  }

  surRedimension();
  dessiner();

  function destroy(): void {
    try {
      simulation.on("tick", null);
      simulation.stop();
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerUp);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("dblclick", onDblClick);
      if (observer) observer.disconnect();
      else window.removeEventListener("resize", surRedimension);
    } catch (e) {
      console.error("[GRAPH] Erreur pendant destroy:", e);
    }
  }

  return { destroy };
}
