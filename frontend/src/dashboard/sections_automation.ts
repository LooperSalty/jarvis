/**
 * Section "Automatisation" : routines programmees + triggers contextuels.
 *
 * ROUTINES (planificateur horaire) :
 *   dash_routines_list -> dash_routines {routines}
 *   dash_routine_save {routine} -> dash_routines {routines}
 *   dash_routine_delete {id}    -> dash_routines {routines}
 *   dash_routine_run {id}       -> dash_routine_run {id, ok}
 *
 * TRIGGERS (reaction au lancement/fermeture de process, via psutil) :
 *   dash_triggers_list -> dash_triggers {triggers, psutil}
 *   dash_trigger_save {trigger} -> dash_triggers {triggers, psutil}
 *   dash_trigger_delete {id}    -> dash_triggers {triggers, psutil}
 *
 * Regle de securite : tout contenu serveur passe par textContent (helpers el()),
 * jamais d'innerHTML. Les donnees serveur sont narrowees via asString/asArray...
 */

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
  switchToggle,
  showToast,
  asString,
  asBool,
  asArray,
  asRecord,
} from "./sections";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Routine {
  id: string;
  nom: string;
  heure: string;
  jours: number[];
  commande: string;
  actif: boolean;
}

type TriggerEvent = "lancement" | "fermeture";

interface Trigger {
  id: string;
  nom: string;
  processus: string;
  evenement: TriggerEvent;
  commande: string;
  actif: boolean;
}

// Libelles courts des jours (0=lundi .. 6=dimanche), alignes sur le backend.
const JOURS_LABELS: readonly string[] = [
  "Lun",
  "Mar",
  "Mer",
  "Jeu",
  "Ven",
  "Sam",
  "Dim",
];

// ── Narrowing des donnees serveur ─────────────────────────────────────────────

function parseRoutines(raw: unknown): Routine[] {
  return asArray(raw).map((r) => {
    const rec = asRecord(r);
    const jours = asArray(rec.jours)
      .map((j) => (typeof j === "number" ? j : Number.NaN))
      .filter((j) => Number.isInteger(j) && j >= 0 && j <= 6);
    return {
      id: asString(rec.id),
      nom: asString(rec.nom),
      heure: asString(rec.heure, "08:00"),
      jours,
      commande: asString(rec.commande),
      actif: asBool(rec.actif),
    };
  });
}

function parseTriggers(raw: unknown): Trigger[] {
  return asArray(raw).map((t) => {
    const rec = asRecord(t);
    const evenement: TriggerEvent =
      asString(rec.evenement) === "fermeture" ? "fermeture" : "lancement";
    return {
      id: asString(rec.id),
      nom: asString(rec.nom),
      processus: asString(rec.processus),
      evenement,
      commande: asString(rec.commande),
      actif: asBool(rec.actif),
    };
  });
}

/** Formate la liste de jours en libelle lisible ("Tous les jours" si vide). */
function formatJours(jours: number[]): string {
  if (jours.length === 0) return "Tous les jours";
  return [...jours]
    .sort((a, b) => a - b)
    .map((j) => JOURS_LABELS[j] ?? "?")
    .join(", ");
}

// ── Rendu d'une ligne de routine ──────────────────────────────────────────────

function buildRoutineRow(routine: Routine): HTMLElement {
  const row = el("div", "auto-row");

  const main = el("div", "auto-main");
  const title = el("div", "auto-title");
  title.appendChild(el("strong", "", routine.nom || "(sans nom)"));
  title.appendChild(el("span", "auto-badge neutral", routine.heure));
  title.appendChild(el("span", "auto-badge", formatJours(routine.jours)));
  main.appendChild(title);
  if (routine.commande) {
    main.appendChild(el("code", "auto-cmd", routine.commande));
  }
  row.appendChild(main);

  const controls = el("div", "auto-controls");

  const toggle = switchToggle(routine.actif);
  toggle.root.title = routine.actif ? "Desactiver" : "Activer";
  toggle.input.addEventListener("change", () => {
    const maj: Routine = { ...routine, actif: toggle.input.checked };
    if (!ws.send({ type: "dash_routine_save", routine: maj })) {
      showToast("Backend deconnecte.", false);
      toggle.input.checked = !toggle.input.checked;
    }
  });
  controls.appendChild(toggle.root);

  const testBtn = button("Tester", "ghost");
  testBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_routine_run", id: routine.id })) {
      showToast("Backend deconnecte.", false);
    }
  });
  controls.appendChild(testBtn);

  const delBtn = button("Supprimer", "danger");
  delBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_routine_delete", id: routine.id })) {
      showToast("Backend deconnecte.", false);
    }
  });
  controls.appendChild(delBtn);

  row.appendChild(controls);
  return row;
}

// ── Rendu d'une ligne de trigger ──────────────────────────────────────────────

function buildTriggerRow(trigger: Trigger): HTMLElement {
  const row = el("div", "auto-row");

  const main = el("div", "auto-main");
  const title = el("div", "auto-title");
  title.appendChild(el("strong", "", trigger.nom || "(sans nom)"));
  title.appendChild(
    el(
      "span",
      "auto-badge neutral",
      trigger.evenement === "fermeture" ? "Fermeture" : "Lancement"
    )
  );
  if (trigger.processus) {
    title.appendChild(el("code", "auto-proc", trigger.processus));
  }
  main.appendChild(title);
  if (trigger.commande) {
    main.appendChild(el("code", "auto-cmd", trigger.commande));
  }
  row.appendChild(main);

  const controls = el("div", "auto-controls");

  const toggle = switchToggle(trigger.actif);
  toggle.root.title = trigger.actif ? "Desactiver" : "Activer";
  toggle.input.addEventListener("change", () => {
    const maj: Trigger = { ...trigger, actif: toggle.input.checked };
    if (!ws.send({ type: "dash_trigger_save", trigger: maj })) {
      showToast("Backend deconnecte.", false);
      toggle.input.checked = !toggle.input.checked;
    }
  });
  controls.appendChild(toggle.root);

  const delBtn = button("Supprimer", "danger");
  delBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_trigger_delete", id: trigger.id })) {
      showToast("Backend deconnecte.", false);
    }
  });
  controls.appendChild(delBtn);

  row.appendChild(controls);
  return row;
}

// ── Montage de la section ─────────────────────────────────────────────────────

function mount(root: HTMLElement): Cleanup {
  // ════════════════════════════ Bloc ROUTINES ════════════════════════════
  const pRoutines = panel(
    "Routines programmees",
    "Rejoue une commande automatiquement a une heure et des jours donnes"
  );
  const routinesBox = el("div", "auto-list");
  pRoutines.body.appendChild(routinesBox);

  // Formulaire d'ajout d'une routine.
  const rNom = textInput("Nom (ex : Meteo du matin)");
  const rHeure = el("input", "input") as HTMLInputElement;
  rHeure.type = "time";
  rHeure.value = "08:00";
  const rCommande = textInput("Commande (ex : quelle est la meteo)");

  const rForm = el("div", "form-row");
  rForm.appendChild(labeledField("Nom", rNom));
  rForm.appendChild(labeledField("Heure", rHeure));
  rForm.appendChild(labeledField("Commande", rCommande));
  pRoutines.body.appendChild(rForm);

  // Cases a cocher des jours (Lun..Dim). Vide = tous les jours.
  const joursBox = el("div", "auto-days");
  const joursInputs: HTMLInputElement[] = [];
  for (let i = 0; i < JOURS_LABELS.length; i++) {
    const wrap = el("label", "auto-day");
    const cb = el("input") as HTMLInputElement;
    cb.type = "checkbox";
    cb.value = String(i);
    wrap.appendChild(cb);
    wrap.appendChild(el("span", "", JOURS_LABELS[i]));
    joursBox.appendChild(wrap);
    joursInputs.push(cb);
  }
  pRoutines.body.appendChild(
    labeledField("Jours (aucun coche = tous les jours)", joursBox)
  );

  const rAddBtn = button("Ajouter la routine", "primary");
  pRoutines.body.appendChild(rAddBtn);
  root.appendChild(pRoutines.root);

  // ════════════════════════════ Bloc TRIGGERS ════════════════════════════
  const pTriggers = panel(
    "Triggers contextuels",
    "Reagit au lancement ou a la fermeture d'une application"
  );
  // Note affichee si psutil est indisponible (surveillance impossible).
  const triggersNote = el("div", "auto-note");
  triggersNote.style.display = "none";
  pTriggers.body.appendChild(triggersNote);

  const triggersBox = el("div", "auto-list");
  pTriggers.body.appendChild(triggersBox);

  const tNom = textInput("Nom (ex : Au demarrage de VS Code)");
  const tProcessus = textInput("Processus (ex : Code.exe, chrome, spotify)");
  const tEvenement = el("select", "input") as HTMLSelectElement;
  const optLancement = el("option", "", "Lancement");
  optLancement.value = "lancement";
  const optFermeture = el("option", "", "Fermeture");
  optFermeture.value = "fermeture";
  tEvenement.appendChild(optLancement);
  tEvenement.appendChild(optFermeture);
  const tCommande = textInput("Commande (ex : mets de la musique)");

  const tForm = el("div", "form-row");
  tForm.appendChild(labeledField("Nom", tNom));
  tForm.appendChild(labeledField("Processus", tProcessus));
  tForm.appendChild(labeledField("Evenement", tEvenement));
  tForm.appendChild(labeledField("Commande", tCommande));
  pTriggers.body.appendChild(tForm);

  const tAddBtn = button("Ajouter le trigger", "primary");
  pTriggers.body.appendChild(tAddBtn);
  root.appendChild(pTriggers.root);

  // Garde l'etat psutil pour (de)griser le formulaire de triggers.
  let psutilOk = true;

  // ── Rendu des listes ──
  function renderRoutines(routines: Routine[]): void {
    clearChildren(routinesBox);
    if (routines.length === 0) {
      routinesBox.appendChild(
        el("div", "empty", "Aucune routine programmee.")
      );
      return;
    }
    for (const routine of routines) {
      routinesBox.appendChild(buildRoutineRow(routine));
    }
  }

  function setTriggersNote(message: string): void {
    if (message) {
      triggersNote.textContent = message;
      triggersNote.style.display = "";
    } else {
      triggersNote.textContent = "";
      triggersNote.style.display = "none";
    }
  }

  function setTriggerFormEnabled(enabled: boolean): void {
    for (const ctrl of [tNom, tProcessus, tEvenement, tCommande, tAddBtn]) {
      ctrl.disabled = !enabled;
    }
  }

  function renderTriggers(triggers: Trigger[]): void {
    clearChildren(triggersBox);
    if (!psutilOk) {
      triggersBox.appendChild(
        el(
          "div",
          "empty",
          "Surveillance des processus indisponible sur cette machine."
        )
      );
      return;
    }
    if (triggers.length === 0) {
      triggersBox.appendChild(el("div", "empty", "Aucun trigger configure."));
      return;
    }
    for (const trigger of triggers) {
      triggersBox.appendChild(buildTriggerRow(trigger));
    }
  }

  // ── Ajout d'une routine ──
  rAddBtn.addEventListener("click", () => {
    const nom = rNom.value.trim();
    const heure = rHeure.value.trim() || "08:00";
    const commande = rCommande.value.trim();
    if (!nom || !commande) {
      showToast("Nom et commande sont obligatoires.", false);
      return;
    }
    const jours = joursInputs
      .filter((cb) => cb.checked)
      .map((cb) => Number(cb.value))
      .filter((j) => Number.isInteger(j));
    const routine = { nom, heure, jours, commande, actif: true };
    if (ws.send({ type: "dash_routine_save", routine })) {
      rNom.value = "";
      rHeure.value = "08:00";
      rCommande.value = "";
      for (const cb of joursInputs) cb.checked = false;
    } else {
      showToast("Backend deconnecte.", false);
    }
  });

  // ── Ajout d'un trigger ──
  tAddBtn.addEventListener("click", () => {
    const nom = tNom.value.trim();
    const processus = tProcessus.value.trim();
    const commande = tCommande.value.trim();
    const evenement =
      tEvenement.value === "fermeture" ? "fermeture" : "lancement";
    if (!nom || !processus || !commande) {
      showToast("Nom, processus et commande sont obligatoires.", false);
      return;
    }
    const trigger = { nom, processus, evenement, commande, actif: true };
    if (ws.send({ type: "dash_trigger_save", trigger })) {
      tNom.value = "";
      tProcessus.value = "";
      tCommande.value = "";
      tEvenement.value = "lancement";
    } else {
      showToast("Backend deconnecte.", false);
    }
  });

  function fetchAll(): void {
    ws.send({ type: "dash_routines_list" });
    ws.send({ type: "dash_triggers_list" });
  }

  // ── Abonnements WS ──
  const offRoutines = ws.on("dash_routines", (msg) => {
    const error = asString(msg.error);
    if (error) showToast(error, false);
    renderRoutines(parseRoutines(msg.routines));
  });
  const offRoutineRun = ws.on("dash_routine_run", (msg) => {
    if (asBool(msg.ok)) showToast("Routine lancee.");
    else showToast("Impossible de lancer la routine.", false);
  });
  const offTriggers = ws.on("dash_triggers", (msg) => {
    const error = asString(msg.error);
    if (error) showToast(error, false);
    psutilOk = asBool(msg.psutil);
    setTriggerFormEnabled(psutilOk);
    setTriggersNote(
      psutilOk
        ? ""
        : "psutil indisponible : impossible de surveiller les processus. " +
            "Installe la dependance puis redemarre Jarvis."
    );
    renderTriggers(parseTriggers(msg.triggers));
  });
  const offStatus = ws.onStatus((ok) => {
    if (ok) fetchAll();
  });

  if (ws.isConnected()) fetchAll();
  renderRoutines([]);
  renderTriggers([]);

  return () => {
    offRoutines();
    offRoutineRun();
    offTriggers();
    offStatus();
  };
}

export const sectionAutomation: Section = {
  id: "automation",
  label: "Automatisation",
  icon: "⏰",
  mount,
};
