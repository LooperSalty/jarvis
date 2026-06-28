/**
 * Onglet "Operator" : assistant operationnel (tri mail, RDV, reunion, devis,
 * recherche). Socle (Phase 1) : file d'approbation + journal d'activite.
 *
 * Securite : tout contenu serveur passe par les helpers DOM (textContent),
 * jamais d'innerHTML avec des donnees. Contrat WS :
 *   -> dash_operator_init                  (demande l'etat)
 *   <- dash_operator_state {pending, activity}
 *   -> dash_operator_confirm {id} / dash_operator_reject {id}
 *   <- dash_operator_pending {pending, ok, message}
 *   <- operator_activity {evenement}       (push live, on rafraichit)
 */

import * as ws from "./ws";
import {
  type Section,
  el,
  panel,
  button,
  showToast,
  asArray,
  asRecord,
  asString,
} from "./sections";

export const sectionOperator: Section = {
  id: "operator",
  label: "Operator",
  icon: "🛰️",
  mount(root: HTMLElement) {
    const { root: pPending, body: pendingBody } = panel(
      "À valider",
      "Devis et réponses email en attente de votre accord."
    );
    const { root: pActivity, body: activityBody } = panel(
      "Activité récente",
      "Ce que l'Operator a fait (tri mail, RDV, devis...)."
    );
    root.appendChild(pPending);
    root.appendChild(pActivity);

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
        valider.addEventListener("click", () =>
          ws.send({ type: "dash_operator_confirm", id })
        );
        const rejeter = button("Rejeter", "danger");
        rejeter.addEventListener("click", () =>
          ws.send({ type: "dash_operator_reject", id })
        );
        row.appendChild(valider);
        row.appendChild(rejeter);
        pendingBody.appendChild(row);
      }
    };

    const renderActivity = (items: unknown[]): void => {
      activityBody.replaceChildren();
      if (!items.length) {
        activityBody.appendChild(el("p", "muted", "—"));
        return;
      }
      // Plus recent en haut.
      for (const raw of items.slice().reverse()) {
        const rec = asRecord(raw);
        const ts = asString(rec.ts);
        const type = asString(rec.type);
        const detail = asString(rec.detail);
        const line = el("div", "op-log");
        line.appendChild(el("span", "op-log-ts", ts));
        line.appendChild(el("span", "op-log-type", type));
        if (detail) line.appendChild(el("span", "op-log-detail", detail));
        activityBody.appendChild(line);
      }
    };

    const offState = ws.on("dash_operator_state", (msg) => {
      renderPending(asArray(asRecord(msg).pending));
      renderActivity(asArray(asRecord(msg).activity));
    });
    const offPending = ws.on("dash_operator_pending", (msg) => {
      const rec = asRecord(msg);
      renderPending(asArray(rec.pending));
      const message = asString(rec.message);
      if (message) showToast(message, rec.ok === true);
    });
    const offActivity = ws.on("operator_activity", () => {
      ws.send({ type: "dash_operator_init" });
    });

    const demander = (): void => {
      ws.send({ type: "dash_operator_init" });
    };
    if (ws.isConnected()) demander();
    const offStatus = ws.onStatus((connecte: boolean) => {
      if (connecte) demander();
    });

    return () => {
      offState();
      offPending();
      offActivity();
      offStatus();
    };
  },
};
