/**
 * Section "Connecteurs" : serveurs MCP + skills.
 *
 * MCP : dash_mcp_list / dash_mcp_add / dash_mcp_remove / dash_mcp_toggle
 *       / dash_mcp_tools (accordeon des tools par serveur).
 * Skills : dash_skills_list / dash_skill_toggle (renvoie la liste rafraichie).
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
  asNumber,
  asArray,
  asRecord,
} from "./sections";

interface McpServer {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  connected: boolean;
  nbTools: number;
}

function parseServers(raw: unknown): McpServer[] {
  return asArray(raw).map((s) => {
    const r = asRecord(s);
    return {
      name: asString(r.name),
      command: asString(r.command),
      args: asArray(r.args).map((a) => asString(a)),
      enabled: asBool(r.enabled),
      connected: asBool(r.connected),
      nbTools: asNumber(r.nb_tools, 0),
    };
  });
}

/** Entree du catalogue MCP preconfigure (renvoyee par dash_mcp_catalog). */
interface McpCatalogEntry {
  nom: string;
  description: string;
  command: string;
  args: string[];
  besoin: string;
}

function parseCatalog(raw: unknown): McpCatalogEntry[] {
  return asArray(raw).map((c) => {
    const r = asRecord(c);
    return {
      nom: asString(r.nom),
      description: asString(r.description),
      command: asString(r.command),
      args: asArray(r.args).map((a) => asString(a)),
      besoin: asString(r.besoin),
    };
  });
}

/** Construit une ligne serveur MCP avec son accordeon de tools. */
function buildServerRow(
  server: McpServer,
  openTools: Set<string>
): HTMLElement {
  const row = el("div", "mcp-row");
  row.dataset.name = server.name;

  const head = el("div", "mcp-head");
  const main = el("div", "mcp-main");
  const title = el("div", "mcp-title");
  title.appendChild(el("strong", "", server.name));
  title.appendChild(
    el("span", `mcp-badge ${server.connected ? "ok" : "off"}`,
      server.connected ? "connecte" : "deconnecte")
  );
  title.appendChild(el("span", "mcp-badge neutral", `${server.nbTools} tools`));
  main.appendChild(title);
  main.appendChild(
    el("code", "mcp-cmd", [server.command, ...server.args].join(" "))
  );
  head.appendChild(main);

  const controls = el("div", "mcp-controls");
  const toggle = switchToggle(server.enabled);
  toggle.root.title = server.enabled ? "Desactiver" : "Activer";
  toggle.input.addEventListener("change", () => {
    if (!ws.send({
      type: "dash_mcp_toggle",
      name: server.name,
      enabled: toggle.input.checked,
    })) {
      showToast("Backend deconnecte.", false);
      toggle.input.checked = !toggle.input.checked;
    }
  });
  controls.appendChild(toggle.root);

  const toolsBtn = button("Voir les tools", "ghost");
  controls.appendChild(toolsBtn);

  const removeBtn = button("Supprimer", "danger");
  removeBtn.addEventListener("click", () => {
    if (!ws.send({ type: "dash_mcp_remove", name: server.name })) {
      showToast("Backend deconnecte.", false);
    }
  });
  controls.appendChild(removeBtn);
  head.appendChild(controls);
  row.appendChild(head);

  const accordion = el("div", "mcp-tools hidden");
  row.appendChild(accordion);

  toolsBtn.addEventListener("click", () => {
    const willOpen = accordion.classList.contains("hidden");
    accordion.classList.toggle("hidden", !willOpen);
    if (willOpen) {
      openTools.add(server.name);
      clearChildren(accordion);
      accordion.appendChild(el("div", "empty", "Chargement..."));
      if (!ws.send({ type: "dash_mcp_tools", name: server.name })) {
        showToast("Backend deconnecte.", false);
      }
    } else {
      openTools.delete(server.name);
    }
  });

  return row;
}

function renderToolsInto(accordion: HTMLElement, msg: ws.WsMessage): void {
  clearChildren(accordion);
  const error = asString(msg.error);
  if (error) {
    accordion.appendChild(el("div", "empty err", error));
    return;
  }
  const tools = asArray(msg.tools);
  if (tools.length === 0) {
    accordion.appendChild(el("div", "empty", "Aucun tool expose."));
    return;
  }
  for (const raw of tools) {
    const t = asRecord(raw);
    const item = el("div", "mcp-tool");
    item.appendChild(el("strong", "", asString(t.name)));
    item.appendChild(el("span", "", asString(t.description)));
    accordion.appendChild(item);
  }
}

/** Construit une ligne du catalogue MCP avec son bouton d'ajout en 1 clic. */
function buildCatalogRow(entry: McpCatalogEntry): HTMLElement {
  const row = el("div", "mcp-catalog-row");

  const main = el("div", "mcp-catalog-main");
  const title = el("div", "mcp-catalog-title");
  title.appendChild(el("strong", "", entry.nom));
  main.appendChild(title);
  main.appendChild(el("span", "mcp-catalog-desc", entry.description));
  main.appendChild(
    el("code", "mcp-catalog-cmd", [entry.command, ...entry.args].join(" "))
  );
  if (entry.besoin) {
    main.appendChild(el("span", "mcp-catalog-need hint", entry.besoin));
  }
  row.appendChild(main);

  const controls = el("div", "mcp-catalog-controls");
  // Si un argument doit etre edite (chemin, dossier...), on propose un champ
  // pre-rempli avec le dernier argument du modele ; sinon ajout direct.
  let argInput: HTMLInputElement | null = null;
  if (entry.besoin && entry.args.length > 0) {
    argInput = textInput("Argument a editer", entry.args[entry.args.length - 1]);
    controls.appendChild(labeledField("Argument", argInput));
  }

  const addBtn = button("Ajouter", "primary");
  addBtn.addEventListener("click", () => {
    // Recompose les args en remplacant le dernier par la valeur editee.
    const args = [...entry.args];
    if (argInput) {
      const edite = argInput.value.trim();
      if (!edite) {
        showToast("L'argument a editer ne peut pas etre vide.", false);
        return;
      }
      args[args.length - 1] = edite;
    }
    if (
      ws.send({
        type: "dash_mcp_add",
        name: entry.nom,
        command: entry.command,
        args,
      })
    ) {
      showToast(`Ajout du serveur ${entry.nom}...`);
    } else {
      showToast("Backend deconnecte.", false);
    }
  });
  controls.appendChild(addBtn);
  row.appendChild(controls);

  return row;
}

function mount(root: HTMLElement): Cleanup {
  // ── Bloc MCP ──
  const pMcp = panel(
    "Serveurs MCP",
    "Connecte Jarvis a des outils externes via le Model Context Protocol"
  );
  const serversBox = el("div", "mcp-list");
  pMcp.body.appendChild(serversBox);

  const addName = textInput("Nom (ex : filesystem)");
  const addCommand = textInput("Commande (ex : npx)");
  const addArgs = textInput("Arguments separes par espaces");
  const addBtn = button("Ajouter le serveur", "primary");
  const addForm = el("div", "form-row");
  addForm.appendChild(labeledField("Nom", addName));
  addForm.appendChild(labeledField("Commande", addCommand));
  addForm.appendChild(labeledField("Arguments", addArgs));
  addForm.appendChild(addBtn);
  pMcp.body.appendChild(addForm);
  root.appendChild(pMcp.root);

  // ── Bloc Catalogue MCP (ajout en 1 clic) ──
  const pCatalog = panel(
    "Catalogue MCP",
    "Serveurs MCP preconfigures, prets a ajouter en un clic"
  );
  const catalogBox = el("div", "mcp-catalog-list");
  pCatalog.body.appendChild(catalogBox);
  const browseBtn = button("Parcourir le catalogue", "ghost");
  browseBtn.addEventListener("click", () => {
    clearChildren(catalogBox);
    catalogBox.appendChild(el("div", "empty", "Chargement..."));
    if (!ws.send({ type: "dash_mcp_catalog" })) {
      showToast("Backend deconnecte.", false);
      clearChildren(catalogBox);
    }
  });
  pCatalog.body.appendChild(browseBtn);
  pCatalog.body.appendChild(
    el(
      "p",
      "hint",
      "Les cles des connecteurs Spotify, Telegram, Discord et OpenClaw se " +
        "renseignent dans la section Vue d'ensemble."
    )
  );
  root.appendChild(pCatalog.root);

  // ── Bloc Skills ──
  const pSkills = panel(
    "Skills",
    "Capacites declaratives chargees depuis le dossier jarvis_skills/"
  );
  const skillsBox = el("div", "skills-list");
  pSkills.body.appendChild(skillsBox);
  pSkills.body.appendChild(
    el(
      "p",
      "hint",
      "Depose un fichier de skill dans jarvis_skills/ a la racine du projet : " +
        "il apparaitra ici et pourra etre active ou desactive sans redemarrer."
    )
  );
  root.appendChild(pSkills.root);

  // ── Bloc Skills Claude Code (Cowork) ──
  const pCcSkills = panel(
    "Skills Claude Code (Cowork)",
    "Ajoute en un clic des collections de skills a Claude Code : elles boostent le Cowork et la commande jcode."
  );
  const ccSkillsBox = el("div", "skills-list");
  ccSkillsBox.appendChild(el("div", "empty", "Chargement..."));
  pCcSkills.body.appendChild(ccSkillsBox);
  root.appendChild(pCcSkills.root);

  // Serveurs dont l'accordeon est ouvert (conserve entre re-rendus)
  const openTools = new Set<string>();

  function renderServers(servers: McpServer[]): void {
    clearChildren(serversBox);
    if (servers.length === 0) {
      serversBox.appendChild(el("div", "empty", "Aucun serveur MCP configure."));
      return;
    }
    for (const server of servers) {
      const row = buildServerRow(server, openTools);
      serversBox.appendChild(row);
      // re-ouvre l'accordeon si l'utilisateur l'avait laisse ouvert
      if (openTools.has(server.name)) {
        const accordion = row.querySelector(".mcp-tools") as HTMLElement | null;
        if (accordion) {
          accordion.classList.remove("hidden");
          accordion.appendChild(el("div", "empty", "Chargement..."));
          ws.send({ type: "dash_mcp_tools", name: server.name });
        }
      }
    }
  }

  function renderCatalog(entries: McpCatalogEntry[]): void {
    clearChildren(catalogBox);
    if (entries.length === 0) {
      catalogBox.appendChild(el("div", "empty", "Catalogue vide."));
      return;
    }
    for (const entry of entries) {
      catalogBox.appendChild(buildCatalogRow(entry));
    }
  }

  function renderSkills(raw: unknown): void {
    clearChildren(skillsBox);
    const skills = asArray(raw);
    if (skills.length === 0) {
      skillsBox.appendChild(el("div", "empty", "Aucune skill detectee."));
      return;
    }
    for (const rawSkill of skills) {
      const s = asRecord(rawSkill);
      const nom = asString(s.nom);
      const row = el("div", "skill-row");
      const main = el("div", "skill-main");
      main.appendChild(el("strong", "", nom));
      main.appendChild(el("span", "skill-desc", asString(s.description)));
      if (asString(s.fichier)) {
        main.appendChild(el("code", "skill-file", asString(s.fichier)));
      }
      row.appendChild(main);

      const toggle = switchToggle(asBool(s.active));
      toggle.input.addEventListener("change", () => {
        if (!ws.send({
          type: "dash_skill_toggle",
          nom,
          enabled: toggle.input.checked,
        })) {
          showToast("Backend deconnecte.", false);
          toggle.input.checked = !toggle.input.checked;
        }
      });
      row.appendChild(toggle.root);
      skillsBox.appendChild(row);
    }
  }

  function renderCcSkills(msg: ws.WsMessage): void {
    clearChildren(ccSkillsBox);
    if (!asBool(msg.claude_present)) {
      ccSkillsBox.appendChild(
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
      ccSkillsBox.appendChild(el("div", "empty", "Catalogue vide."));
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
      ccSkillsBox.appendChild(row);
    }
  }

  function fetchAll(): void {
    ws.send({ type: "dash_mcp_list" });
    ws.send({ type: "dash_skills_list" });
    ws.send({ type: "dash_cc_skills" });
  }

  addBtn.addEventListener("click", () => {
    const name = addName.value.trim();
    const command = addCommand.value.trim();
    if (!name || !command) {
      showToast("Nom et commande sont obligatoires.", false);
      return;
    }
    const args = addArgs.value.trim().split(/\s+/).filter(Boolean);
    if (ws.send({ type: "dash_mcp_add", name, command, args })) {
      addName.value = "";
      addCommand.value = "";
      addArgs.value = "";
    } else {
      showToast("Backend deconnecte.", false);
    }
  });

  // ── Abonnements WS ──
  const offList = ws.on("dash_mcp_list", (msg) => {
    renderServers(parseServers(msg.servers));
  });
  const offSaved = ws.on("dash_mcp_saved", (msg) => {
    if (asBool(msg.ok)) showToast("Configuration MCP mise a jour.");
    else showToast(asString(msg.error, "Echec de l'operation MCP."), false);
    ws.send({ type: "dash_mcp_list" });
  });
  const offCatalog = ws.on("dash_mcp_catalog", (msg) => {
    renderCatalog(parseCatalog(msg.catalogue));
  });
  const offTools = ws.on("dash_mcp_tools", (msg) => {
    const name = asString(msg.name);
    const row = serversBox.querySelector(
      `.mcp-row[data-name="${CSS.escape(name)}"]`
    );
    const accordion = row?.querySelector(".mcp-tools") as HTMLElement | null;
    if (accordion) renderToolsInto(accordion, msg);
  });
  const offSkills = ws.on("dash_skills_list", (msg) => {
    renderSkills(msg.skills);
  });
  const offCcSkills = ws.on("dash_cc_skills", (msg) => {
    renderCcSkills(msg);
  });
  const offCcAdded = ws.on("dash_cc_skill_added", (msg) => {
    if (asBool(msg.ok)) showToast(asString(msg.message, "Skill ajoutee."));
    else showToast(asString(msg.message, "Echec de l'ajout."), false);
    ws.send({ type: "dash_cc_skills" });
  });
  const offStatus = ws.onStatus((ok) => {
    if (ok) fetchAll();
  });

  if (ws.isConnected()) fetchAll();
  renderServers([]);
  renderSkills([]);

  return () => {
    offList();
    offSaved();
    offCatalog();
    offTools();
    offSkills();
    offCcSkills();
    offCcAdded();
    offStatus();
  };
}

export const sectionConnectors: Section = {
  id: "connectors",
  label: "Connecteurs",
  icon: "🔌",
  mount,
};
