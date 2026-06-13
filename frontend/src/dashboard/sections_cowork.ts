/**
 * Section "Cowork" (inspiree de Claude Cowork) :
 * - Definir un DOSSIER de travail precis (persiste dans jarvis_ui_config.json).
 * - Voir son etat : existence, statut git (branche / modifications), apercu.
 * - Confier une tache a Claude Code qui s'execute DANS ce dossier (claude_bridge).
 *
 * Protocole WS :
 *   -> dash_cowork_status            <- dash_cowork {folder, exists, git, entries...}
 *   -> dash_set_cowork {folder}      <- dash_cowork
 *   -> dash_cowork_delegate {prompt} <- dash_cowork_result {ok, output|error}
 */

import * as ws from "./ws";
import {
  type Section,
  type Cleanup,
  el,
  clearChildren,
  panel,
  button,
  textInput,
  labeledField,
  showToast,
  asRecord,
  asString,
  asBool,
  asNumber,
  asArray,
} from "./sections";

function mount(root: HTMLElement): Cleanup {
  let claudeDispo = false;
  let dossierValide = false;

  // ── Panneau dossier de travail ──
  const folderPanel = panel(
    "Dossier de travail",
    "Le dossier dans lequel Jarvis et Claude Code travailleront."
  );
  const statusEl = el("div", "cowork-status");
  folderPanel.body.appendChild(statusEl);

  const folderInput = textInput("C:\\Users\\moi\\mon-projet", "");
  const setBtn = button("Definir le dossier", "primary");
  const clearBtn = button("Retirer", "danger");
  const folderRow = el("div", "form-row");
  folderRow.appendChild(labeledField("Chemin du dossier", folderInput));
  folderRow.appendChild(setBtn);
  folderRow.appendChild(clearBtn);
  folderPanel.body.appendChild(folderRow);
  root.appendChild(folderPanel.root);

  // ── Panneau delegation a Claude Code ──
  const taskPanel = panel(
    "Confier une tache a Claude Code",
    "Claude Code s'execute dans le dossier ci-dessus et renvoie sa reponse."
  );
  const taskInput = el("textarea", "input cowork-task") as HTMLTextAreaElement;
  taskInput.placeholder = "Decris la tache a realiser dans ce dossier...";
  taskInput.rows = 3;
  taskInput.spellcheck = false;
  const runBtn = button("Confier a Claude Code", "primary");
  taskPanel.body.appendChild(labeledField("Tache", taskInput));
  taskPanel.body.appendChild(runBtn);
  const resultEl = el("div", "cowork-result hidden");
  taskPanel.body.appendChild(resultEl);
  root.appendChild(taskPanel.root);

  function majBoutonRun(): void {
    runBtn.disabled = !(claudeDispo && dossierValide);
  }

  function renderStatus(msg: ws.WsMessage): void {
    const folder = asString(msg.folder);
    const exists = asBool(msg.exists);
    claudeDispo = asBool(msg.claude_dispo);
    dossierValide = exists;

    clearChildren(statusEl);
    if (!folder) {
      statusEl.appendChild(el("p", "panel-note", "Aucun dossier defini pour l'instant."));
    } else {
      statusEl.appendChild(el("code", "cowork-path", folder));
      if (!exists) {
        statusEl.appendChild(el("p", "empty err", "Dossier introuvable."));
      } else {
        const meta = el("div", "cowork-meta");
        const git = asRecord(msg.git);
        if (asBool(git.is_repo)) {
          const dirty = asNumber(git.dirty);
          meta.appendChild(
            el(
              "span",
              "cowork-chip",
              `git: ${asString(git.branch, "?")}${dirty ? ` · ${dirty} modif.` : " · propre"}`
            )
          );
        }
        meta.appendChild(el("span", "cowork-chip", `${asNumber(msg.file_count)} elements`));
        statusEl.appendChild(meta);

        const entries = asArray(msg.entries);
        if (entries.length) {
          const list = el("div", "cowork-files");
          for (const brut of entries) {
            const e = asRecord(brut);
            const item = el("span", "cowork-file");
            item.appendChild(el("span", "cowork-file-ico", asBool(e.dir) ? "📁" : "📄"));
            item.appendChild(el("span", "", asString(e.name)));
            list.appendChild(item);
          }
          statusEl.appendChild(list);
        }
      }
    }
    if (!claudeDispo) {
      statusEl.appendChild(
        el(
          "p",
          "panel-note",
          "Claude Code (commande 'claude') introuvable dans le PATH : la delegation est indisponible."
        )
      );
    }
    folderInput.value = folder;
    majBoutonRun();
  }

  setBtn.addEventListener("click", () => {
    const f = folderInput.value.trim();
    if (!ws.send({ type: "dash_set_cowork", folder: f })) {
      showToast("Backend deconnecte.", false);
    }
  });

  clearBtn.addEventListener("click", () => {
    folderInput.value = "";
    if (!ws.send({ type: "dash_set_cowork", folder: "" })) {
      showToast("Backend deconnecte.", false);
    }
  });

  runBtn.addEventListener("click", () => {
    const tache = taskInput.value.trim();
    if (!tache) {
      showToast("Decris d'abord la tache.", false);
      return;
    }
    resultEl.classList.remove("hidden");
    clearChildren(resultEl);
    resultEl.appendChild(
      el("p", "panel-note", "Claude Code travaille dans le dossier… (cela peut prendre un moment)")
    );
    runBtn.disabled = true;
    if (!ws.send({ type: "dash_cowork_delegate", prompt: tache })) {
      showToast("Backend deconnecte.", false);
      majBoutonRun();
    }
  });

  // ── Abonnements WS ──
  const offCowork = ws.on("dash_cowork", (msg) => {
    if (asString(msg.error)) showToast(asString(msg.error), false);
    renderStatus(msg);
  });

  const offResult = ws.on("dash_cowork_result", (msg) => {
    majBoutonRun();
    clearChildren(resultEl);
    resultEl.classList.remove("hidden");
    if (!asBool(msg.ok)) {
      resultEl.appendChild(el("p", "empty err", asString(msg.error, "Echec de la delegation.")));
      return;
    }
    resultEl.appendChild(el("div", "cowork-output", asString(msg.output, "(reponse vide)")));
  });

  const offStatus = ws.onStatus((ok) => {
    if (ok) ws.send({ type: "dash_cowork_status" });
  });

  if (ws.isConnected()) ws.send({ type: "dash_cowork_status" });

  return () => {
    offCowork();
    offResult();
    offStatus();
  };
}

export const sectionCowork: Section = {
  id: "cowork",
  label: "Cowork",
  icon: "📂",
  mount,
};
