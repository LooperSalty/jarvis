/**
 * Section "Profil" : formulaire complet de jarvis_profile.json.
 *
 * Schema (toutes les cles optionnelles) :
 *   identite: {prenom, surnom_prefere, date_naissance, metier}
 *   famille: [{nom, relation, notes}]
 *   adresse: {rue, ville, code_postal, pays}
 *   habitudes: [str] / preferences: [str]
 *   routines: [{quand, quoi}]
 *   notes_libres: str
 *
 * Charge via dash_get_profile, sauve via dash_set_profile.
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
  showToast,
  asString,
  asBool,
  asArray,
  asRecord,
} from "./sections";

/** Cree une ligne dynamique : N inputs (dataset.k = cle) + bouton supprimer. */
function dynamicRow(
  fields: ReadonlyArray<{ key: string; placeholder: string; value: string }>
): HTMLElement {
  const row = el("div", "dyn-row");
  for (const f of fields) {
    const input = textInput(f.placeholder, f.value);
    input.dataset.k = f.key;
    row.appendChild(input);
  }
  const remove = button("✕", "danger");
  remove.classList.add("btn-icon");
  remove.title = "Supprimer";
  remove.addEventListener("click", () => row.remove());
  row.appendChild(remove);
  return row;
}

/** Lit toutes les lignes dynamiques d'un conteneur en objets {cle: valeur}. */
function readRows(box: HTMLElement): Array<Record<string, string>> {
  const out: Array<Record<string, string>> = [];
  for (const row of Array.from(box.querySelectorAll(".dyn-row"))) {
    const entry: Record<string, string> = {};
    for (const input of Array.from(row.querySelectorAll("input"))) {
      const key = input.dataset.k ?? "";
      if (key) entry[key] = input.value.trim();
    }
    if (Object.values(entry).some((v) => v !== "")) out.push(entry);
  }
  return out;
}

/** Bloc liste dynamique : conteneur + bouton ajouter. */
function dynamicList(
  body: HTMLElement,
  addLabel: string,
  makeRow: () => HTMLElement
): HTMLElement {
  const box = el("div", "dyn-list");
  body.appendChild(box);
  const add = button(addLabel, "ghost");
  add.addEventListener("click", () => box.appendChild(makeRow()));
  body.appendChild(add);
  return box;
}

function mount(root: HTMLElement): Cleanup {
  // ── Identite ──
  const pIdent = panel("Identite");
  const inpPrenom = textInput("Prenom");
  const inpSurnom = textInput("Surnom prefere");
  const inpNaissance = textInput("Date de naissance (JJ/MM/AAAA)");
  const inpMetier = textInput("Metier");
  const identGrid = el("div", "field-grid");
  identGrid.appendChild(labeledField("Prenom", inpPrenom));
  identGrid.appendChild(labeledField("Surnom prefere", inpSurnom));
  identGrid.appendChild(labeledField("Date de naissance", inpNaissance));
  identGrid.appendChild(labeledField("Metier", inpMetier));
  pIdent.body.appendChild(identGrid);
  root.appendChild(pIdent.root);

  // ── Adresse ──
  const pAdr = panel("Adresse");
  const inpRue = textInput("Rue");
  const inpVille = textInput("Ville");
  const inpCp = textInput("Code postal");
  const inpPays = textInput("Pays");
  const adrGrid = el("div", "field-grid");
  adrGrid.appendChild(labeledField("Rue", inpRue));
  adrGrid.appendChild(labeledField("Ville", inpVille));
  adrGrid.appendChild(labeledField("Code postal", inpCp));
  adrGrid.appendChild(labeledField("Pays", inpPays));
  pAdr.body.appendChild(adrGrid);
  root.appendChild(pAdr.root);

  // ── Famille ──
  const pFam = panel("Famille", "Proches que Jarvis doit connaitre");
  const familleRow = (nom = "", relation = "", notes = "") =>
    dynamicRow([
      { key: "nom", placeholder: "Nom", value: nom },
      { key: "relation", placeholder: "Relation (femme, fils...)", value: relation },
      { key: "notes", placeholder: "Notes", value: notes },
    ]);
  const famBox = dynamicList(pFam.body, "+ Ajouter un proche", () => familleRow());
  root.appendChild(pFam.root);

  // ── Habitudes / Preferences ──
  const pHab = panel("Habitudes");
  const habitudeRow = (v = "") =>
    dynamicRow([{ key: "valeur", placeholder: "Habitude", value: v }]);
  const habBox = dynamicList(pHab.body, "+ Ajouter une habitude", () => habitudeRow());
  root.appendChild(pHab.root);

  const pPref = panel("Preferences");
  const prefRow = (v = "") =>
    dynamicRow([{ key: "valeur", placeholder: "Preference", value: v }]);
  const prefBox = dynamicList(pPref.body, "+ Ajouter une preference", () => prefRow());
  root.appendChild(pPref.root);

  // ── Routines ──
  const pRout = panel("Routines", "Ex : quand = le matin, quoi = resume meteo + agenda");
  const routineRow = (quand = "", quoi = "") =>
    dynamicRow([
      { key: "quand", placeholder: "Quand", value: quand },
      { key: "quoi", placeholder: "Quoi", value: quoi },
    ]);
  const routBox = dynamicList(pRout.body, "+ Ajouter une routine", () => routineRow());
  root.appendChild(pRout.root);

  // ── Notes libres ──
  const pNotes = panel("Notes libres");
  const notesArea = el("textarea", "input textarea") as HTMLTextAreaElement;
  notesArea.rows = 5;
  notesArea.placeholder = "Tout ce que Jarvis doit savoir d'autre...";
  pNotes.body.appendChild(notesArea);
  root.appendChild(pNotes.root);

  // ── Barre d'actions ──
  const actions = el("div", "actions-bar");
  const saveBtn = button("Enregistrer le profil", "primary");
  const reloadBtn = button("Recharger", "ghost");
  actions.appendChild(saveBtn);
  actions.appendChild(reloadBtn);
  root.appendChild(actions);

  // ── Lecture / ecriture du profil ──
  function collect(): Record<string, unknown> {
    return {
      identite: {
        prenom: inpPrenom.value.trim(),
        surnom_prefere: inpSurnom.value.trim(),
        date_naissance: inpNaissance.value.trim(),
        metier: inpMetier.value.trim(),
      },
      famille: readRows(famBox),
      adresse: {
        rue: inpRue.value.trim(),
        ville: inpVille.value.trim(),
        code_postal: inpCp.value.trim(),
        pays: inpPays.value.trim(),
      },
      habitudes: readRows(habBox).map((r) => r.valeur ?? ""),
      preferences: readRows(prefBox).map((r) => r.valeur ?? ""),
      routines: readRows(routBox),
      notes_libres: notesArea.value.trim(),
    };
  }

  function populate(profile: Record<string, unknown>): void {
    const ident = asRecord(profile.identite);
    inpPrenom.value = asString(ident.prenom);
    inpSurnom.value = asString(ident.surnom_prefere);
    inpNaissance.value = asString(ident.date_naissance);
    inpMetier.value = asString(ident.metier);

    const adr = asRecord(profile.adresse);
    inpRue.value = asString(adr.rue);
    inpVille.value = asString(adr.ville);
    inpCp.value = asString(adr.code_postal);
    inpPays.value = asString(adr.pays);

    clearChildren(famBox);
    for (const raw of asArray(profile.famille)) {
      const f = asRecord(raw);
      famBox.appendChild(
        familleRow(asString(f.nom), asString(f.relation), asString(f.notes))
      );
    }

    clearChildren(habBox);
    for (const raw of asArray(profile.habitudes)) {
      habBox.appendChild(habitudeRow(asString(raw)));
    }
    clearChildren(prefBox);
    for (const raw of asArray(profile.preferences)) {
      prefBox.appendChild(prefRow(asString(raw)));
    }

    clearChildren(routBox);
    for (const raw of asArray(profile.routines)) {
      const r = asRecord(raw);
      routBox.appendChild(routineRow(asString(r.quand), asString(r.quoi)));
    }

    notesArea.value = asString(profile.notes_libres);
  }

  function fetchProfile(): void {
    ws.send({ type: "dash_get_profile" });
  }

  saveBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_set_profile", profile: collect() })) {
      showToast("Backend deconnecte.", false);
    }
  });
  reloadBtn.addEventListener("click", fetchProfile);

  let loaded = false;
  const offProfile = ws.on("dash_profile", (msg) => {
    loaded = true;
    populate(asRecord(msg.profile));
  });
  const offSaved = ws.on("dash_profile_saved", (msg) => {
    if (asBool(msg.ok)) showToast("Profil enregistre.");
    else showToast(asString(msg.error, "Echec de l'enregistrement du profil."), false);
  });
  // Re-fetch a la connexion uniquement si jamais charge :
  // on ne veut pas ecraser une saisie en cours apres une reconnexion.
  const offStatus = ws.onStatus((ok) => {
    if (ok && !loaded) fetchProfile();
  });

  if (ws.isConnected()) fetchProfile();

  return () => {
    offProfile();
    offSaved();
    offStatus();
  };
}

export const sectionProfile: Section = {
  id: "profile",
  label: "Profil",
  icon: "👤",
  mount,
};
