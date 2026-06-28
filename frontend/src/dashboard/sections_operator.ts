/**
 * Onglet "Operator" : assistant operationnel (tri mail, RDV, reunion, devis,
 * recherche). Panneaux : A valider (approbations), Reunion (live + import),
 * Recherche, Reglages (societe/devis/autonomie/regles), Activite.
 *
 * Securite : tout contenu serveur passe par les helpers DOM (textContent),
 * jamais d'innerHTML avec des donnees. Contrat WS (type -> action) :
 *   dash_operator_init        -> dash_operator_state {pending, activity}
 *   dash_operator_confirm/reject {id} -> dash_operator_pending {pending, ok, message}
 *   dash_operator_settings_get/set    -> dash_operator_settings {config, ok}
 *   dash_operator_meeting {op,path}   -> dash_operator_meeting {ok, message, actif, transcript}
 *   dash_operator_research {query}    -> dash_operator_research {resume, sources}
 *   dash_operator_devis {description} -> dash_operator_pending {pending, ok, message}
 *   operator_activity / operator_pending / operator_transcript : push live
 */

import * as ws from "./ws";
import {
  type Section,
  el,
  panel,
  button,
  textInput,
  labeledField,
  showToast,
  asArray,
  asBool,
  asNumber,
  asRecord,
  asString,
} from "./sections";

export const sectionOperator: Section = {
  id: "operator",
  label: "Operator",
  icon: "🛰️",
  mount(root: HTMLElement) {
    const offs: Array<() => void> = [];

    // ── A valider ────────────────────────────────────────────────
    const { root: pPending, body: pendingBody } = panel(
      "À valider",
      "Devis et réponses email en attente de votre accord (« oui » / « non »)."
    );
    const renderPending = (items: unknown[]): void => {
      pendingBody.replaceChildren();
      if (!items.length) {
        pendingBody.appendChild(el("p", "muted", "Aucune action en attente."));
        return;
      }
      for (const raw of items) {
        const rec = asRecord(raw);
        const id = asString(rec.id);
        const resume = asString(rec.resume) || asString(rec.type) || "Action";
        const row = el("div", "op-item");
        row.appendChild(el("span", "op-item-label", resume));
        const valider = button("Valider", "primary");
        valider.addEventListener("click", () => ws.send({ type: "dash_operator_confirm", id }));
        const rejeter = button("Rejeter", "danger");
        rejeter.addEventListener("click", () => ws.send({ type: "dash_operator_reject", id }));
        row.appendChild(valider);
        row.appendChild(rejeter);
        pendingBody.appendChild(row);
      }
    };

    // ── Reunion ──────────────────────────────────────────────────
    const { root: pMeeting, body: meetingBody } = panel(
      "Réunion",
      "Écoute en direct ou import d'un enregistrement, puis génération de devis."
    );
    const meetingStatus = el("p", "muted", "Inactif.");
    const transcriptBox = el("div", "op-transcript");
    transcriptBox.textContent = "—";
    const btnStart = button("Démarrer l'écoute", "primary");
    const btnStop = button("Arrêter", "danger");
    const importPath = textInput("Chemin d'un fichier audio (mp3/wav)…");
    const btnImport = button("Importer + transcrire", "ghost");
    const btnDevis = button("Générer un devis depuis la réunion", "ghost");
    btnStart.addEventListener("click", () => ws.send({ type: "dash_operator_meeting", op: "start" }));
    btnStop.addEventListener("click", () => ws.send({ type: "dash_operator_meeting", op: "stop" }));
    btnImport.addEventListener("click", () =>
      ws.send({ type: "dash_operator_meeting", op: "import", path: importPath.value })
    );
    btnDevis.addEventListener("click", () => ws.send({ type: "dash_operator_devis", description: "" }));
    const ctrl = el("div", "op-row");
    ctrl.appendChild(btnStart);
    ctrl.appendChild(btnStop);
    meetingBody.appendChild(ctrl);
    meetingBody.appendChild(meetingStatus);
    meetingBody.appendChild(el("span", "field-label", "Transcript"));
    meetingBody.appendChild(transcriptBox);
    meetingBody.appendChild(labeledField("Import audio", importPath));
    const importRow = el("div", "op-row");
    importRow.appendChild(btnImport);
    importRow.appendChild(btnDevis);
    meetingBody.appendChild(importRow);

    const setMeeting = (actif: boolean, transcript: string): void => {
      meetingStatus.textContent = actif ? "Écoute en cours…" : "Inactif.";
      if (transcript) transcriptBox.textContent = transcript;
    };

    // ── Recherche ────────────────────────────────────────────────
    const { root: pSearch, body: searchBody } = panel("Recherche", "Recherche internet + synthèse.");
    const searchInput = textInput("Que veux-tu rechercher ?");
    const btnSearch = button("Rechercher", "primary");
    const searchResult = el("div", "op-search-result");
    const runSearch = (): void => {
      const q = searchInput.value.trim();
      if (q) {
        searchResult.textContent = "Recherche en cours…";
        ws.send({ type: "dash_operator_research", query: q });
      }
    };
    btnSearch.addEventListener("click", runSearch);
    searchInput.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") runSearch();
    });
    const searchRow = el("div", "op-row");
    searchRow.appendChild(searchInput);
    searchRow.appendChild(btnSearch);
    searchBody.appendChild(searchRow);
    searchBody.appendChild(searchResult);

    // ── Reglages ─────────────────────────────────────────────────
    const { root: pSettings, body: settingsBody } = panel(
      "Réglages Operator",
      "Société (pour les devis), niveau d'autonomie email, TVA, numérotation."
    );
    const fNom = textInput("Nom de la société");
    const fAdresse = textInput("Adresse");
    const fSiret = textInput("SIRET");
    const fEmail = textInput("Email société");
    const fTel = textInput("Téléphone");
    const fIban = textInput("IBAN (optionnel)");
    const fAutonomie = el("select", "input") as HTMLSelectElement;
    for (const [val, lib] of [
      ["tri_auto_reponses_validees", "Tri auto + réponses validées"],
      ["tout_en_validation", "Tout en validation"],
      ["autonomie_totale", "Autonomie totale"],
      ["tri_auto_seul", "Tri auto seulement"],
    ] as const) {
      const opt = el("option") as HTMLOptionElement;
      opt.value = val;
      opt.textContent = lib;
      fAutonomie.appendChild(opt);
    }
    const fIntervalle = textInput("15");
    fIntervalle.type = "number";
    const fPrefixe = textInput("DEV");
    const fTva = textInput("20");
    fTva.type = "number";
    const fValidite = textInput("30");
    fValidite.type = "number";
    const fMentions = el("textarea", "input") as HTMLTextAreaElement;
    fMentions.rows = 2;
    fMentions.placeholder = "Mentions légales du devis";

    settingsBody.appendChild(labeledField("Société", fNom));
    settingsBody.appendChild(labeledField("Adresse", fAdresse));
    const grid = el("div", "op-grid");
    grid.appendChild(labeledField("SIRET", fSiret));
    grid.appendChild(labeledField("Email", fEmail));
    grid.appendChild(labeledField("Téléphone", fTel));
    grid.appendChild(labeledField("IBAN", fIban));
    settingsBody.appendChild(grid);
    settingsBody.appendChild(labeledField("Autonomie email", fAutonomie));
    settingsBody.appendChild(labeledField("Intervalle de tri (min)", fIntervalle));
    const grid2 = el("div", "op-grid");
    grid2.appendChild(labeledField("Préfixe devis", fPrefixe));
    grid2.appendChild(labeledField("TVA par défaut (%)", fTva));
    grid2.appendChild(labeledField("Validité (jours)", fValidite));
    settingsBody.appendChild(grid2);
    settingsBody.appendChild(labeledField("Mentions devis", fMentions));
    const btnSave = button("Enregistrer", "primary");
    btnSave.addEventListener("click", () => {
      ws.send({
        type: "dash_operator_settings_set",
        updates: {
          societe: {
            nom: fNom.value, adresse: fAdresse.value, siret: fSiret.value,
            email: fEmail.value, tel: fTel.value, iban: fIban.value,
          },
          autonomie_email: fAutonomie.value,
          triage_intervalle_min: Number(fIntervalle.value) || 15,
          devis: {
            prefixe: fPrefixe.value, tva_taux_defaut: Number(fTva.value) || 20,
            validite_jours: Number(fValidite.value) || 30, mentions: fMentions.value,
          },
        },
      });
    });
    settingsBody.appendChild(btnSave);

    const fillSettings = (cfg: Record<string, unknown>): void => {
      const soc = asRecord(cfg.societe);
      fNom.value = asString(soc.nom);
      fAdresse.value = asString(soc.adresse);
      fSiret.value = asString(soc.siret);
      fEmail.value = asString(soc.email);
      fTel.value = asString(soc.tel);
      fIban.value = asString(soc.iban);
      const aut = asString(cfg.autonomie_email);
      if (aut) fAutonomie.value = aut;
      fIntervalle.value = String(asNumber(cfg.triage_intervalle_min, 15));
      const dev = asRecord(cfg.devis);
      fPrefixe.value = asString(dev.prefixe) || "DEV";
      fTva.value = String(asNumber(dev.tva_taux_defaut, 20));
      fValidite.value = String(asNumber(dev.validite_jours, 30));
      fMentions.value = asString(dev.mentions);
    };

    // ── Activite ─────────────────────────────────────────────────
    const { root: pActivity, body: activityBody } = panel(
      "Activité récente",
      "Ce que l'Operator a fait (tri mail, RDV, devis…)."
    );
    const renderActivity = (items: unknown[]): void => {
      activityBody.replaceChildren();
      if (!items.length) {
        activityBody.appendChild(el("p", "muted", "—"));
        return;
      }
      for (const raw of items.slice().reverse()) {
        const rec = asRecord(raw);
        const line = el("div", "op-log");
        line.appendChild(el("span", "op-log-ts", asString(rec.ts)));
        line.appendChild(el("span", "op-log-type", asString(rec.type)));
        const detail = asString(rec.detail);
        if (detail) line.appendChild(el("span", "op-log-detail", detail));
        activityBody.appendChild(line);
      }
    };

    root.appendChild(pPending);
    root.appendChild(pMeeting);
    root.appendChild(pSearch);
    root.appendChild(pSettings);
    root.appendChild(pActivity);

    // ── Abonnements WS ───────────────────────────────────────────
    offs.push(ws.on("dash_operator_state", (m) => {
      const r = asRecord(m);
      renderPending(asArray(r.pending));
      renderActivity(asArray(r.activity));
    }));
    offs.push(ws.on("dash_operator_pending", (m) => {
      const r = asRecord(m);
      renderPending(asArray(r.pending));
      const message = asString(r.message);
      if (message) showToast(message, asBool(r.ok));
    }));
    offs.push(ws.on("operator_activity", () => ws.send({ type: "dash_operator_init" })));
    // Approbation poussee en direct (ex: brouillon cree par le tri mail de fond).
    offs.push(ws.on("operator_pending", (m) => renderPending(asArray(asRecord(m).pending))));
    offs.push(ws.on("operator_transcript", (m) => {
      const chunk = asString(asRecord(m).chunk);
      if (!chunk) return;
      const prev = transcriptBox.textContent === "—" ? "" : transcriptBox.textContent ?? "";
      transcriptBox.textContent = (prev + " " + chunk).trim();
    }));
    offs.push(ws.on("dash_operator_settings", (m) => {
      const r = asRecord(m);
      fillSettings(asRecord(r.config));
      if (asBool(r.ok)) showToast("Réglages enregistrés", true);
    }));
    offs.push(ws.on("dash_operator_meeting", (m) => {
      const r = asRecord(m);
      setMeeting(asBool(r.actif), asString(r.transcript));
      const message = asString(r.message);
      if (message) showToast(message, asBool(r.ok));
    }));
    offs.push(ws.on("dash_operator_research", (m) => {
      const r = asRecord(m);
      const resume = asString(r.resume) || "Aucun résultat.";
      const sources = asArray(r.sources);
      searchResult.replaceChildren();
      searchResult.appendChild(el("p", "op-search-resume", resume));
      for (const s of sources) {
        const sr = asRecord(s);
        const item = el("div", "op-source");
        item.appendChild(el("span", "op-source-title", asString(sr.titre)));
        const lien = asString(sr.lien);
        // N'autorise que http(s) (jamais javascript:/data: meme via SerpAPI).
        if (lien && /^https?:\/\//i.test(lien)) {
          const a = el("a", "op-source-link", lien) as HTMLAnchorElement;
          a.href = lien;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          item.appendChild(a);
        }
        searchResult.appendChild(item);
      }
    }));

    const demander = (): void => {
      ws.send({ type: "dash_operator_init" });
      ws.send({ type: "dash_operator_settings_get" });
      ws.send({ type: "dash_operator_meeting", op: "state" });
    };
    if (ws.isConnected()) demander();
    offs.push(ws.onStatus((c: boolean) => { if (c) demander(); }));

    return () => { for (const off of offs) off(); };
  },
};
