/**
 * Section "Skills" (sous-onglet Parametres) : catalogue de skills Claude Code
 * installables en un clic, pour booster le Cowork et la commande jcode/jarvis.
 *
 * Protocole WS :
 *   -> dash_cc_skills            <- dash_cc_skills {claude_present, catalogue, installes}
 *   -> dash_cc_skill_add {repo}  <- dash_cc_skill_added {ok, message}
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

function mount(root: HTMLElement): Cleanup {
  const p = panel(
    "Skills Claude Code",
    "Ajoute en un clic des collections de skills a Claude Code : elles boostent le Cowork et les sessions de code (jcode / jarvis)."
  );
  const box = el("div", "skills-list");
  box.appendChild(el("div", "empty", "Chargement..."));
  p.body.appendChild(box);
  root.appendChild(p.root);

  function render(msg: ws.WsMessage): void {
    clearChildren(box);
    if (!asBool(msg.claude_present)) {
      box.appendChild(
        el(
          "div",
          "empty",
          "Claude Code (claude) n'est pas installe ou pas dans le PATH."
        )
      );
      return;
    }
    const installes = new Set(
      asArray(msg.installes).map((r) => asString(r).toLowerCase())
    );
    const cat = asArray(msg.catalogue);
    if (cat.length === 0) {
      box.appendChild(el("div", "empty", "Catalogue vide."));
      return;
    }
    for (const rawEntry of cat) {
      const e = asRecord(rawEntry);
      const repo = asString(e.repo);
      const row = el("div", "skill-row");
      const main = el("div", "skill-main");
      main.appendChild(el("strong", "", asString(e.nom)));
      main.appendChild(el("span", "skill-desc", asString(e.description)));
      main.appendChild(el("code", "skill-file", repo));
      row.appendChild(main);

      if (installes.has(repo.toLowerCase())) {
        const done = button("Deja ajoute", "ghost");
        done.disabled = true;
        row.appendChild(done);
      } else {
        const addBtn = button("Ajouter", "primary");
        addBtn.addEventListener("click", () => {
          addBtn.disabled = true;
          addBtn.textContent = "Ajout...";
          if (!ws.send({ type: "dash_cc_skill_add", repo })) {
            showToast("Backend deconnecte.", false);
            addBtn.disabled = false;
            addBtn.textContent = "Ajouter";
          }
        });
        row.appendChild(addBtn);
      }
      box.appendChild(row);
    }
  }

  function fetch(): void {
    ws.send({ type: "dash_cc_skills" });
  }

  const offSkills = ws.on("dash_cc_skills", (msg) => render(msg));
  const offAdded = ws.on("dash_cc_skill_added", (msg) => {
    if (asBool(msg.ok)) showToast(asString(msg.message, "Skill ajoutee."));
    else showToast(asString(msg.message, "Echec de l'ajout."), false);
    fetch();
  });
  const offStatus = ws.onStatus((ok) => {
    if (ok) fetch();
  });

  if (ws.isConnected()) fetch();

  return () => {
    offSkills();
    offAdded();
    offStatus();
  };
}

export const sectionCcSkills: Section = {
  id: "cc-skills",
  label: "Skills",
  icon: "🧩",
  mount,
};
