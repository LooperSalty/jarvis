/**
 * Section "Skills" (sous-onglet Parametres) : deux catalogues de skills
 * installables en un clic, pour booster le Cowork et jcode/jarvis.
 *
 *  1. Marketplaces Claude Code  (claude plugin marketplace add <repo>)
 *  2. Skills skills.sh          (npx skills add <repo> -a claude-code -g)
 *
 * Protocole WS :
 *   -> dash_cc_skills            <- dash_cc_skills {claude_present, catalogue, installes}
 *   -> dash_cc_skill_add {repo}  <- dash_cc_skill_added {ok, message}
 *   -> dash_skills_sh            <- dash_skills_sh {npx_present, catalogue}
 *   -> dash_skills_sh_add {repo} <- dash_skills_sh_added {ok, message}
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
  asArray,
  asRecord,
} from "./sections";

// Construit une ligne "skill" avec un bouton d'action.
function ligneSkill(
  e: Record<string, unknown>,
  dejaInstalle: boolean,
  onAdd: (repo: string, btn: HTMLButtonElement) => void
): HTMLElement {
  const repo = asString(e.repo);
  const row = el("div", "skill-row");
  const main = el("div", "skill-main");
  main.appendChild(el("strong", "", asString(e.nom)));
  main.appendChild(el("span", "skill-desc", asString(e.description)));
  main.appendChild(el("code", "skill-file", repo));
  row.appendChild(main);

  if (dejaInstalle) {
    const done = button("Deja ajoute", "ghost");
    done.disabled = true;
    row.appendChild(done);
  } else {
    const addBtn = button("Ajouter", "primary");
    addBtn.addEventListener("click", () => {
      addBtn.disabled = true;
      addBtn.textContent = "Ajout...";
      onAdd(repo, addBtn);
    });
    row.appendChild(addBtn);
  }
  return row;
}

function mount(root: HTMLElement): Cleanup {
  // ── Panneau 1 : marketplaces Claude Code ──
  const p1 = panel(
    "Marketplaces Claude Code",
    "Ajoute en un clic des collections de skills a Claude Code (via claude plugin marketplace). Boostent le Cowork et les sessions de code (jcode / jarvis)."
  );
  const box1 = el("div", "skills-list");
  box1.appendChild(el("div", "empty", "Chargement..."));
  p1.body.appendChild(box1);
  root.appendChild(p1.root);

  // ── Panneau 2 : skills skills.sh ──
  const p2 = panel(
    "Skills skills.sh",
    "Catalogue du registre ouvert skills.sh, installes globalement via npx skills add (dispo dans tous les projets : Cowork, jcode)."
  );
  const box2 = el("div", "skills-list");
  box2.appendChild(el("div", "empty", "Chargement..."));
  p2.body.appendChild(box2);
  root.appendChild(p2.root);

  // ── Rendu panneau 1 (marketplaces) ──
  function renderMarketplaces(msg: ws.WsMessage): void {
    clearChildren(box1);
    if (!asBool(msg.claude_present)) {
      box1.appendChild(
        el("div", "empty", "Claude Code (claude) n'est pas installe ou pas dans le PATH.")
      );
      return;
    }
    const installes = new Set(
      asArray(msg.installes).map((r) => asString(r).toLowerCase())
    );
    const cat = asArray(msg.catalogue);
    if (cat.length === 0) {
      box1.appendChild(el("div", "empty", "Catalogue vide."));
      return;
    }
    for (const rawEntry of cat) {
      const e = asRecord(rawEntry);
      const repo = asString(e.repo);
      box1.appendChild(
        ligneSkill(e, installes.has(repo.toLowerCase()), (r) => {
          if (!ws.send({ type: "dash_cc_skill_add", repo: r })) {
            showToast("Backend deconnecte.", false);
            fetchMarketplaces();
          }
        })
      );
    }
  }

  // ── Rendu panneau 2 (skills.sh) ──
  function renderSkillsSh(msg: ws.WsMessage): void {
    clearChildren(box2);
    if (!asBool(msg.npx_present)) {
      box2.appendChild(
        el("div", "empty", "npx (Node.js) n'est pas installe ou pas dans le PATH.")
      );
      return;
    }
    const cat = asArray(msg.catalogue);
    if (cat.length === 0) {
      box2.appendChild(el("div", "empty", "Catalogue vide."));
      return;
    }
    for (const rawEntry of cat) {
      const e = asRecord(rawEntry);
      // skills.sh : pas de detection d'installation (npx skills add est idempotent).
      box2.appendChild(
        ligneSkill(e, false, (r, btn) => {
          if (!ws.send({ type: "dash_skills_sh_add", repo: r })) {
            showToast("Backend deconnecte.", false);
            btn.disabled = false;
            btn.textContent = "Ajouter";
          }
        })
      );
    }
  }

  function fetchMarketplaces(): void {
    ws.send({ type: "dash_cc_skills" });
  }
  function fetchSkillsSh(): void {
    ws.send({ type: "dash_skills_sh" });
  }

  const offSkills = ws.on("dash_cc_skills", (msg) => renderMarketplaces(msg));
  const offAdded = ws.on("dash_cc_skill_added", (msg) => {
    if (asBool(msg.ok)) showToast(asString(msg.message, "Marketplace ajoutee."));
    else showToast(asString(msg.message, "Echec de l'ajout."), false);
    fetchMarketplaces();
  });
  const offShList = ws.on("dash_skills_sh", (msg) => renderSkillsSh(msg));
  const offShAdded = ws.on("dash_skills_sh_added", (msg) => {
    if (asBool(msg.ok)) showToast(asString(msg.message, "Skill installe."));
    else showToast(asString(msg.message, "Echec de l'installation."), false);
    fetchSkillsSh();
  });
  const offStatus = ws.onStatus((ok) => {
    if (ok) {
      fetchMarketplaces();
      fetchSkillsSh();
    }
  });

  if (ws.isConnected()) {
    fetchMarketplaces();
    fetchSkillsSh();
  }

  return () => {
    offSkills();
    offAdded();
    offShList();
    offShAdded();
    offStatus();
  };
}

export const sectionCcSkills: Section = {
  id: "cc-skills",
  label: "Skills",
  icon: "🧩",
  mount,
};
