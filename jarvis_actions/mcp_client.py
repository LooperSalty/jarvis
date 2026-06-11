"""Client MCP (Model Context Protocol) minimal en stdio pour Jarvis.

Aucune dependance externe : json + asyncio.create_subprocess_exec uniquement.

Transport stdio MCP : messages JSON-RPC 2.0 delimites par des sauts de ligne
(une ligne = un message JSON complet). Handshake :
1. requete "initialize" (protocolVersion, capabilities, clientInfo)
2. reponse du serveur
3. notification "notifications/initialized"
Ensuite :
- "tools/list" -> result.tools = [{name, description, inputSchema}]
- "tools/call" (params {name, arguments}) -> result.content = [{type: "text", text}]

Config : jarvis_mcp.json a la racine du repo (a cote de main2.py), format :
{"servers": {"nom": {"command": "npx", "args": [...], "env": {}, "enabled": true}}}
Voir jarvis_mcp_example.json pour des exemples prets a copier.

Robustesse : un serveur qui meurt ou timeout ne fait JAMAIS crasher l'appelant.
Toutes les fonctions retournent des erreurs propres (message + bool), jamais
d'exception non geree vers main2.py. Les sessions sont liees au loop asyncio
qui les a demarrees : appeler toujours depuis le meme loop (celui de main2).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess  # uniquement pour CREATE_NO_WINDOW (constante Windows)
import sys
from pathlib import Path

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "jarvis", "version": "1.0"}
_START_TIMEOUT_S = 20.0     # demarrage process + handshake initialize
_LIST_TIMEOUT_S = 15.0      # requete tools/list
_STOP_TIMEOUT_S = 3.0       # attente apres terminate avant kill
_STREAM_LIMIT = 4 * 1024 * 1024  # 4 Mo max par ligne (gros resultats de tools)

# Sessions actives : une par serveur MCP lance
_SESSIONS: dict[str, "_McpSession"] = {}
_START_LOCK = asyncio.Lock()


class _McpSession:
    """Session stdio vers un serveur MCP (un process par serveur).

    IDs JSON-RPC incrementaux ; correlation des reponses par id via le
    dictionnaire pending (les notifications du serveur, sans id, sont ignorees).
    """

    def __init__(self, name: str, proc: asyncio.subprocess.Process) -> None:
        self.name = name
        self.proc = proc
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.tools_cache: list[dict] | None = None
        self.write_lock = asyncio.Lock()
        self.reader_task: asyncio.Task | None = None

    def alive(self) -> bool:
        """True si le process serveur tourne encore."""
        return self.proc.returncode is None


# ============================================================
# Config (jarvis_mcp.json)
# ============================================================

def _config_path() -> Path:
    """Chemin de jarvis_mcp.json (racine du repo, a cote de main2.py)."""
    if getattr(sys, "frozen", False):
        # .exe PyInstaller : __file__ pointe dans le bundle temporaire
        return Path(os.getcwd()) / "jarvis_mcp.json"
    return Path(__file__).resolve().parent.parent / "jarvis_mcp.json"


def charger_config() -> dict:
    """Charge jarvis_mcp.json. Retourne {"servers": {}} si absent/corrompu."""
    path = _config_path()
    try:
        if not path.exists():
            return {"servers": {}}
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict) or not isinstance(cfg.get("servers"), dict):
            print(f"[MCP] Config invalide dans {path.name} (cle 'servers' attendue)")
            return {"servers": {}}
        return cfg
    except Exception as e:
        print(f"[MCP] Erreur lecture config {path.name} : {e}")
        return {"servers": {}}


def sauvegarder_config(cfg: dict) -> bool:
    """Sauvegarde atomique de la config (ecrit .tmp puis os.replace)."""
    if not isinstance(cfg, dict):
        print("[MCP] Config invalide (dict attendu), sauvegarde annulee")
        return False
    path = _config_path()
    tmp = Path(str(path) + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[MCP] Erreur sauvegarde config : {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def ajouter_serveur(name: str, command: str, args: list[str]) -> tuple[str, bool]:
    """Ajoute (ou met a jour) un serveur dans la config. Retourne (message, success)."""
    name = (name or "").strip()
    command = (command or "").strip()
    if not name or name.startswith("_"):
        return "Nom de serveur MCP invalide.", False
    if not command:
        return "Commande invalide pour le serveur MCP.", False
    if not isinstance(args, list):
        return "Les arguments doivent etre une liste de chaines.", False

    cfg = charger_config()
    servers = dict(cfg.get("servers", {}))
    ancien = servers.get(name) if isinstance(servers.get(name), dict) else {}
    existait = name in servers
    # Nouvelle entree (on preserve env/enabled si le serveur existait deja)
    servers = {**servers, name: {
        "command": command,
        "args": [str(a) for a in args],
        "env": dict(ancien.get("env") or {}),
        "enabled": bool(ancien.get("enabled", True)),
    }}
    if not sauvegarder_config({**cfg, "servers": servers}):
        return "Echec de la sauvegarde de la config MCP.", False
    verbe = "mis a jour" if existait else "ajoute"
    return f"Serveur MCP '{name}' {verbe}.", True


def supprimer_serveur(name: str) -> tuple[str, bool]:
    """Supprime un serveur de la config. N'arrete PAS une session deja lancee
    (utiliser arreter_serveur pour ca). Retourne (message, success)."""
    cfg = charger_config()
    servers = dict(cfg.get("servers", {}))
    if name not in servers:
        return f"Serveur MCP '{name}' introuvable dans la config.", False
    servers = {k: v for k, v in servers.items() if k != name}
    if not sauvegarder_config({**cfg, "servers": servers}):
        return "Echec de la sauvegarde de la config MCP.", False
    return f"Serveur MCP '{name}' supprime.", True


def activer_serveur(name: str, enabled: bool) -> tuple[str, bool]:
    """Active/desactive un serveur dans la config. Retourne (message, success)."""
    cfg = charger_config()
    servers = dict(cfg.get("servers", {}))
    srv = servers.get(name)
    if not isinstance(srv, dict):
        return f"Serveur MCP '{name}' introuvable dans la config.", False
    servers = {**servers, name: {**srv, "enabled": bool(enabled)}}
    if not sauvegarder_config({**cfg, "servers": servers}):
        return "Echec de la sauvegarde de la config MCP.", False
    etat = "active" if enabled else "desactive"
    return f"Serveur MCP '{name}' {etat}.", True


# ============================================================
# Transport JSON-RPC 2.0 sur stdio
# ============================================================

async def _send_message(session: _McpSession, msg: dict) -> None:
    """Ecrit un message JSON-RPC (une ligne JSON + \\n) sur le stdin du serveur."""
    if session.proc.stdin is None:
        raise RuntimeError("stdin du serveur ferme")
    data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    async with session.write_lock:
        session.proc.stdin.write(data)
        await session.proc.stdin.drain()


async def _send_request(
    session: _McpSession,
    method: str,
    params: dict | None = None,
    timeout_s: float = 30.0,
) -> dict:
    """Envoie une requete et attend la reponse correlee par id. Retourne result.

    Leve RuntimeError (erreur JSON-RPC ou serveur mort) ou asyncio.TimeoutError.
    """
    if not session.alive():
        raise RuntimeError(f"le process du serveur '{session.name}' est mort")
    session.next_id += 1
    req_id = session.next_id
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    session.pending[req_id] = fut
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    try:
        await _send_message(session, msg)
        reponse = await asyncio.wait_for(fut, timeout=timeout_s)
    finally:
        session.pending.pop(req_id, None)
    if "error" in reponse:
        err = reponse.get("error") or {}
        raise RuntimeError(
            f"{err.get('message', 'erreur JSON-RPC')} (code {err.get('code', '?')})"
        )
    result = reponse.get("result")
    return result if isinstance(result, dict) else {}


def _fail_pending(session: _McpSession, raison: str) -> None:
    """Echoue proprement toutes les requetes en attente (serveur mort/arrete)."""
    for fut in list(session.pending.values()):
        if not fut.done():
            fut.set_exception(RuntimeError(raison))
    session.pending.clear()


async def _dispatch_message(session: _McpSession, msg: dict) -> None:
    """Route un message recu : reponse (id connu), requete serveur, ou notif."""
    msg_id = msg.get("id")
    if "method" in msg:
        if msg_id is not None:
            # Requete venant du serveur (ex: roots/list) : non supportee,
            # on repond une erreur JSON-RPC pour ne pas le laisser bloquer.
            err = {"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": -32601, "message": "Method not supported"}}
            try:
                await _send_message(session, err)
            except Exception:
                pass
        return  # notification serveur (sans id) : ignoree
    if msg_id is None:
        return
    fut = session.pending.get(msg_id)
    if fut is None and isinstance(msg_id, str) and msg_id.isdigit():
        # Certains serveurs renvoient l'id en chaine
        fut = session.pending.get(int(msg_id))
    if fut is not None and not fut.done():
        fut.set_result(msg)


async def _reader_loop(session: _McpSession) -> None:
    """Tache dediee : lit stdout ligne par ligne et correle les reponses."""
    try:
        while True:
            assert session.proc.stdout is not None
            line = await session.proc.stdout.readline()
            if not line:
                break  # EOF : le process serveur s'est termine
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except Exception:
                continue  # ligne non-JSON (log parasite du serveur) : ignoree
            if isinstance(msg, dict):
                await _dispatch_message(session, msg)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[MCP] Lecteur '{session.name}' stoppe : {e}")
    finally:
        _fail_pending(session, f"serveur MCP '{session.name}' deconnecte")


# ============================================================
# Cycle de vie des serveurs
# ============================================================

async def _start_session(name: str, command: str, args: list[str],
                         env: dict[str, str]) -> bool:
    """Lance le process + handshake initialize. A appeler sous _START_LOCK."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = await asyncio.create_subprocess_exec(
        command, *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        limit=_STREAM_LIMIT,
        creationflags=flags,
    )
    session = _McpSession(name, proc)
    _SESSIONS[name] = session  # enregistre tout de suite pour cleanup en cas d'echec
    session.reader_task = asyncio.create_task(
        _reader_loop(session), name=f"mcp-reader-{name}"
    )
    # Handshake MCP : initialize -> reponse -> notification initialized
    params = {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": dict(_CLIENT_INFO),
    }
    result = await _send_request(session, "initialize", params,
                                 timeout_s=_START_TIMEOUT_S)
    await _send_message(session, {"jsonrpc": "2.0",
                                  "method": "notifications/initialized"})
    info = result.get("serverInfo") or {}
    label = f"{info.get('name', '?')} {info.get('version', '')}".strip()
    print(f"[MCP] Connecte a '{name}' ({label})")
    return True


async def demarrer_serveur(name: str) -> bool:
    """Demarre le serveur MCP 'name' (process + handshake). Timeout 20s.

    Idempotent : retourne True direct si la session est deja vivante.
    Ne leve jamais : False + log en cas de probleme.
    """
    session = _SESSIONS.get(name)
    if session is not None and session.alive():
        return True

    cfg = charger_config()
    srv = cfg.get("servers", {}).get(name)
    if not isinstance(srv, dict):
        print(f"[MCP] Serveur '{name}' absent de {_config_path().name}")
        return False
    command = str(srv.get("command", "")).strip()
    if not command:
        print(f"[MCP] Serveur '{name}' : champ 'command' manquant")
        return False
    args = [str(a) for a in (srv.get("args") or [])]
    # Sous Windows, "npx"/"node" sont des .cmd : create_subprocess_exec a
    # besoin du chemin resolu (shell=False, pas de PATHEXT automatique).
    resolved = shutil.which(command) or command
    env_extra = {str(k): str(v) for k, v in (srv.get("env") or {}).items()}
    env = {**os.environ, **env_extra}

    try:
        async with _START_LOCK:
            if name in _SESSIONS and _SESSIONS[name].alive():
                return True  # demarre entre-temps par un autre appel
            return await asyncio.wait_for(
                _start_session(name, resolved, args, env),
                timeout=_START_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        print(f"[MCP] Timeout ({_START_TIMEOUT_S:g}s) au demarrage de '{name}'")
        await arreter_serveur(name)
        return False
    except FileNotFoundError:
        print(f"[MCP] Commande introuvable pour '{name}' : {command}")
        _SESSIONS.pop(name, None)
        return False
    except Exception as e:
        print(f"[MCP] Echec demarrage '{name}' : {e}")
        await arreter_serveur(name)
        return False


async def arreter_serveur(name: str) -> None:
    """Arrete proprement un serveur MCP (terminate puis kill). Ne leve jamais."""
    session = _SESSIONS.pop(name, None)
    if session is None:
        return
    try:
        if session.reader_task is not None:
            session.reader_task.cancel()
    except Exception:
        pass
    try:
        if session.proc.stdin is not None:
            session.proc.stdin.close()
    except Exception:
        pass
    try:
        if session.alive():
            session.proc.terminate()
            try:
                await asyncio.wait_for(session.proc.wait(), timeout=_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                session.proc.kill()
    except ProcessLookupError:
        pass  # deja mort
    except Exception as e:
        print(f"[MCP] Erreur arret '{name}' : {e}")
    _fail_pending(session, f"serveur MCP '{name}' arrete")
    print(f"[MCP] Serveur '{name}' arrete")


async def arreter_tout() -> None:
    """Arrete tous les serveurs MCP actifs (a appeler au quit de Jarvis)."""
    for name in list(_SESSIONS.keys()):
        await arreter_serveur(name)


# ============================================================
# Tools : decouverte + appel
# ============================================================

async def _tools_du_serveur(name: str) -> list[dict]:
    """tools/list pour UN serveur (demarrage lazy + cache). Ne leve jamais."""
    session = _SESSIONS.get(name)
    if session is not None and session.alive() and session.tools_cache is not None:
        return session.tools_cache  # cache valide

    if session is None or not session.alive():
        if not await demarrer_serveur(name):
            return []
        session = _SESSIONS.get(name)
        if session is None:
            return []

    try:
        result = await _send_request(session, "tools/list",
                                     timeout_s=_LIST_TIMEOUT_S)
        tools: list[dict] = []
        for t in result.get("tools") or []:
            if isinstance(t, dict) and t.get("name"):
                tools.append({
                    "server": name,
                    "name": str(t.get("name")),
                    "description": str(t.get("description") or ""),
                    "input_schema": t.get("inputSchema") or {},
                })
        session.tools_cache = tools
        return tools
    except Exception as e:
        print(f"[MCP] tools/list echoue pour '{name}' : {e}")
        return []


async def lister_tools(name: str | None = None) -> list[dict]:
    """Liste les tools : [{server, name, description, input_schema}].

    name=None -> tous les serveurs 'enabled' de la config (demarres a la
    demande, lazy). name='x' -> ce serveur uniquement, meme si desactive.
    Resultat cache par serveur tant que la session vit. Ne leve jamais.
    """
    try:
        cfg = charger_config()
        servers = cfg.get("servers", {})
        if name is not None:
            if name not in servers and name not in _SESSIONS:
                print(f"[MCP] Serveur '{name}' inconnu")
                return []
            cibles = [name]
        else:
            cibles = [
                n for n, s in servers.items()
                if not n.startswith("_")
                and isinstance(s, dict) and s.get("enabled", True)
            ]
        resultat: list[dict] = []
        for srv_name in cibles:
            resultat.extend(await _tools_du_serveur(srv_name))
        return resultat
    except Exception as e:
        print(f"[MCP] Erreur lister_tools : {e}")
        return []


async def appeler_tool(server: str, tool: str, arguments: dict,
                       timeout_s: float = 30) -> tuple[str, bool]:
    """Appelle un tool MCP. Retourne (texte concatene des content text, success).

    En cas de probleme (serveur mort, timeout, erreur JSON-RPC, isError),
    retourne (message d'erreur lisible, False) — ne leve jamais.
    """
    if not isinstance(arguments, dict):
        return "Arguments invalides : un dictionnaire est attendu.", False

    session = _SESSIONS.get(server)
    if session is None or not session.alive():
        if not await demarrer_serveur(server):
            return f"Impossible de demarrer le serveur MCP '{server}'.", False
        session = _SESSIONS.get(server)
        if session is None:
            return f"Session MCP '{server}' introuvable apres demarrage.", False

    try:
        result = await _send_request(
            session, "tools/call",
            {"name": tool, "arguments": arguments},
            timeout_s=timeout_s,
        )
    except asyncio.TimeoutError:
        return (f"Timeout ({timeout_s:g}s) sur le tool '{tool}' "
                f"du serveur '{server}'."), False
    except Exception as e:
        return f"Erreur MCP sur '{server}/{tool}' : {e}", False

    textes: list[str] = []
    for bloc in result.get("content") or []:
        if isinstance(bloc, dict) and bloc.get("type") == "text":
            textes.append(str(bloc.get("text", "")))
    texte = "\n".join(t for t in textes if t).strip()
    if result.get("isError"):
        return (texte or f"Le tool '{tool}' a renvoye une erreur."), False
    return (texte or f"Tool '{tool}' execute (aucun texte renvoye)."), True


def etat_serveurs() -> dict[str, dict]:
    """Etat des serveurs : {name: {"connected": bool, "nb_tools": int}}.

    Couvre les serveurs de la config + les sessions actives hors config.
    """
    try:
        cfg = charger_config()
        noms = [n for n in cfg.get("servers", {}) if not n.startswith("_")]
        for n in _SESSIONS:
            if n not in noms:
                noms.append(n)
        etat: dict[str, dict] = {}
        for n in noms:
            s = _SESSIONS.get(n)
            connected = s is not None and s.alive()
            nb = len(s.tools_cache) if (s is not None and s.tools_cache) else 0
            etat[n] = {"connected": connected, "nb_tools": nb}
        return etat
    except Exception as e:
        print(f"[MCP] Erreur etat_serveurs : {e}")
        return {}
