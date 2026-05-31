"""Expose les actions du Jarvis perso (Meross, PC, Obsidian, dev) comme tools OpenJarvis.

Pourquoi ?
    Une fois enregistres dans la `ToolRegistry` d'OpenJarvis, ces tools peuvent etre
    invoques par un agent OpenJarvis en mode tool-calling. Cela permet a un agent de
    type `orchestrator` ou `native_react` de DECIDER d'appeler `meross_light` ou
    `open_app` selon l'intention detectee dans la requete utilisateur — utile
    pour les phrases ambigues ou multi-actions ("eteins la lampe et ouvre vscode").

Pour le flux normal de main2.py (mots-cles avant IA), ces tools ne changent rien :
    le matching local de pc_actions/dev_actions/meross continue d'avoir la priorite.

Activation :
    appeler `register_jarvis_tools()` une fois au demarrage. Idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional
from jarvis_config import USER_NAME

logger = logging.getLogger(__name__)

_REGISTERED: bool = False


def _run_async(coro) -> Any:
    """Lance une coroutine depuis un contexte sync (utilise par tool.execute).

    Si on est deja dans une event loop, cree une nouvelle loop dans un thread.
    """
    try:
        asyncio.get_running_loop()
        # Une loop tourne deja : on doit utiliser un thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result()
    except RuntimeError:
        # Pas de loop active : on peut creer la notre
        return asyncio.run(coro)


def register_jarvis_tools() -> bool:
    """Enregistre les tools dans ToolRegistry. Idempotent. Retourne True si OK."""
    global _REGISTERED
    if _REGISTERED:
        return True

    try:
        from openjarvis.core.registry import ToolRegistry
        from openjarvis.core.types import ToolResult
        from openjarvis.tools._stubs import BaseTool, ToolSpec
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenJarvis non disponible, skip register_jarvis_tools: %s", exc)
        return False

    # ------------------------------------------------------------------
    # Meross light
    # ------------------------------------------------------------------
    try:
        from jarvis_actions import meross as _meross_mod
    except Exception as exc:  # noqa: BLE001
        logger.warning("meross non importable: %s", exc)
        _meross_mod = None

    if _meross_mod is not None and not ToolRegistry.contains("meross_light"):

        @ToolRegistry.register("meross_light")
        class MerossLightTool(BaseTool):
            tool_id = "meross_light"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="meross_light",
                    description=(
                        "Allume, eteint ou bascule l'etat d'une lumiere connectee Meross. "
                        "Utilise pour controler les lampes intelligentes du domicile."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["on", "off", "toggle"],
                                "description": "Action a effectuer sur la lampe.",
                            },
                            "name_filter": {
                                "type": "string",
                                "description": (
                                    "Sous-chaine pour filtrer la lampe par nom "
                                    "(ex: 'chambre'). Vide = toutes."
                                ),
                            },
                        },
                        "required": ["action"],
                    },
                    category="home",
                    requires_confirmation=False,
                    timeout_seconds=15.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                action = (params.get("action") or "").lower()
                name_filter = params.get("name_filter") or None
                try:
                    if action == "on":
                        ok, msg = _run_async(
                            _meross_mod._switch(target_on=True, name_filter=name_filter)
                        )
                    elif action == "off":
                        ok, msg = _run_async(
                            _meross_mod._switch(target_on=False, name_filter=name_filter)
                        )
                    elif action == "toggle":
                        ok, msg = _run_async(
                            _meross_mod._toggle(name_filter=name_filter)
                        )
                    else:
                        return ToolResult(
                            tool_name="meross_light",
                            content=f"action invalide: {action}",
                            success=False,
                        )
                    return ToolResult(
                        tool_name="meross_light",
                        content=msg or ("ok" if ok else "echec"),
                        success=ok,
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="meross_light",
                        content=f"erreur Meross: {exc}",
                        success=False,
                    )

    # ------------------------------------------------------------------
    # Ouvrir une application / un site
    # ------------------------------------------------------------------
    try:
        from jarvis_actions import pc_actions as _pc_mod
    except Exception as exc:  # noqa: BLE001
        logger.warning("pc_actions non importable: %s", exc)
        _pc_mod = None

    if _pc_mod is not None and not ToolRegistry.contains("open_app"):

        @ToolRegistry.register("open_app")
        class OpenAppTool(BaseTool):
            tool_id = "open_app"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="open_app",
                    description=(
                        "Ouvre une application Windows (chrome, vscode, discord, "
                        "spotify, obsidian...) ou un site web (google maps, youtube, "
                        "gmail, twitter...) ou un fichier/URL."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Nom de l'app ou alias web ou chemin/URL.",
                            }
                        },
                        "required": ["name"],
                    },
                    category="system",
                    timeout_seconds=10.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                name = params.get("name") or ""
                try:
                    msg, ok = _pc_mod._ouvrir_app(name)
                    return ToolResult(
                        tool_name="open_app",
                        content=msg or ("ouvert" if ok else "echec"),
                        success=bool(ok),
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="open_app",
                        content=f"erreur ouverture: {exc}",
                        success=False,
                    )

    if _pc_mod is not None and not ToolRegistry.contains("system_volume"):

        @ToolRegistry.register("system_volume")
        class SystemVolumeTool(BaseTool):
            tool_id = "system_volume"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="system_volume",
                    description=(
                        "Controle le volume systeme Windows : monter, descendre, mute."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["up", "down", "mute"],
                                "description": "Direction du volume.",
                            }
                        },
                        "required": ["action"],
                    },
                    category="system",
                    timeout_seconds=5.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                action = (params.get("action") or "").lower()
                try:
                    msg, ok = _pc_mod._volume(action)
                    return ToolResult(
                        tool_name="system_volume",
                        content=msg,
                        success=bool(ok),
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="system_volume",
                        content=f"erreur volume: {exc}",
                        success=False,
                    )

    # ------------------------------------------------------------------
    # Dev tools (VSCode + git)
    # ------------------------------------------------------------------
    try:
        from jarvis_actions import dev_actions as _dev_mod
    except Exception as exc:  # noqa: BLE001
        logger.warning("dev_actions non importable: %s", exc)
        _dev_mod = None

    if _dev_mod is not None and not ToolRegistry.contains("open_vscode_project"):

        @ToolRegistry.register("open_vscode_project")
        class OpenVscodeProjectTool(BaseTool):
            tool_id = "open_vscode_project"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="open_vscode_project",
                    description=(
                        f"Ouvre un projet de developpement de {USER_NAME} dans VSCode. "
                        "Cherche le projet par nom dans les emplacements connus."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Nom du projet (ex: 'jarvis', 'mon-site').",
                            }
                        },
                        "required": ["name"],
                    },
                    category="dev",
                    timeout_seconds=10.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                name = params.get("name") or ""
                try:
                    msg, ok = _dev_mod._ouvrir_projet_vscode(name)
                    return ToolResult(
                        tool_name="open_vscode_project",
                        content=msg,
                        success=bool(ok),
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="open_vscode_project",
                        content=f"erreur ouverture vscode: {exc}",
                        success=False,
                    )

    if _dev_mod is not None and not ToolRegistry.contains("git_status"):

        @ToolRegistry.register("git_status")
        class GitStatusTool(BaseTool):
            tool_id = "git_status"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="git_status",
                    description="Renvoie le statut git d'un dossier projet local.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Chemin du dossier (vide = projet courant)."
                                ),
                            }
                        },
                    },
                    category="dev",
                    timeout_seconds=15.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                path = params.get("path") or None
                try:
                    msg, ok = _dev_mod._git_status(path)
                    return ToolResult(
                        tool_name="git_status",
                        content=msg,
                        success=bool(ok),
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="git_status",
                        content=f"erreur git: {exc}",
                        success=False,
                    )

    # ------------------------------------------------------------------
    # Obsidian
    # ------------------------------------------------------------------
    _obsidian = _try_get_obsidian_bridge()
    if _obsidian is not None and not ToolRegistry.contains("obsidian_note"):

        @ToolRegistry.register("obsidian_note")
        class ObsidianNoteTool(BaseTool):
            tool_id = "obsidian_note"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="obsidian_note",
                    description=(
                        f"Cree une note dans le vault Obsidian de {USER_NAME}. "
                        "Utilise pour capturer rapidement une idee, un memo, une tache."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Titre de la note (sera slugifie).",
                            },
                            "content": {
                                "type": "string",
                                "description": "Corps de la note en markdown.",
                            },
                        },
                        "required": ["title", "content"],
                    },
                    category="memory",
                    timeout_seconds=5.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                title = params.get("title") or "Note"
                content = params.get("content") or ""
                try:
                    path = _obsidian.save_note(title, content)
                    return ToolResult(
                        tool_name="obsidian_note",
                        content=f"Note enregistree : {path}",
                        success=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="obsidian_note",
                        content=f"erreur obsidian: {exc}",
                        success=False,
                    )

    if _obsidian is not None and not ToolRegistry.contains("obsidian_remember"):

        @ToolRegistry.register("obsidian_remember")
        class ObsidianRememberTool(BaseTool):
            tool_id = "obsidian_remember"
            is_local = True

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="obsidian_remember",
                    description=(
                        f"Memorise un fait persistant pour {USER_NAME} (cle/valeur) dans la "
                        "memoire long-terme synchronisee avec Obsidian."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Cle courte (ex: 'anniversaire_marie').",
                            },
                            "value": {
                                "type": "string",
                                "description": "Valeur associee.",
                            },
                        },
                        "required": ["key", "value"],
                    },
                    category="memory",
                    timeout_seconds=5.0,
                )

            def execute(self, **params: Any) -> ToolResult:
                key = params.get("key") or ""
                value = params.get("value") or ""
                if not key or not value:
                    return ToolResult(
                        tool_name="obsidian_remember",
                        content="key et value requis",
                        success=False,
                    )
                try:
                    path = _obsidian.save_memory(key, value)
                    return ToolResult(
                        tool_name="obsidian_remember",
                        content=f"Memoire sauvee : {path}",
                        success=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(
                        tool_name="obsidian_remember",
                        content=f"erreur memoire: {exc}",
                        success=False,
                    )

    _REGISTERED = True
    return True


def _try_get_obsidian_bridge():
    """Retourne une instance ObsidianBridge si le vault est detectable, sinon None."""
    try:
        from jarvis_actions import obsidian_memory as _ob_mod
    except Exception:
        return None
    try:
        vault = _ob_mod.auto_detect_vault()
        if not vault:
            return None
        return _ob_mod.ObsidianBridge(vault)
    except Exception as exc:  # noqa: BLE001
        logger.info("Obsidian bridge non initialise: %s", exc)
        return None


def list_registered_tools() -> List[str]:
    """Liste les tools que ce module a enregistres et qui sont dispos."""
    try:
        from openjarvis.core.registry import ToolRegistry
    except Exception:  # noqa: BLE001
        return []
    candidates = [
        "meross_light",
        "open_app",
        "system_volume",
        "open_vscode_project",
        "git_status",
        "obsidian_note",
        "obsidian_remember",
    ]
    return [name for name in candidates if ToolRegistry.contains(name)]


__all__ = ["register_jarvis_tools", "list_registered_tools"]
