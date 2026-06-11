/**
 * Client WebSocket du dashboard Jarvis.
 *
 * Singleton module-level :
 * - connect() ouvre la connexion vers ws://<host>:8765 avec reconnexion auto (2s)
 * - send(obj) envoie un objet JSON (retourne false si pas connecte)
 * - on(action, cb) abonne un handler dispatche selon le champ "action"
 * - onStatus(cb) / isConnected() exposent l'etat de connexion (badge UI)
 */

export type WsMessage = { action?: string } & Record<string, unknown>;
export type WsHandler = (msg: WsMessage) => void;
export type StatusHandler = (connected: boolean) => void;

const WS_URL = `ws://${window.location.hostname || "127.0.0.1"}:8765`;
const RECONNECT_INTERVAL_MS = 2_000;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let connected = false;

const handlers = new Map<string, Set<WsHandler>>();
const statusHandlers = new Set<StatusHandler>();

/** Notifie les abonnes au statut uniquement quand l'etat change. */
function notifyStatus(ok: boolean): void {
  if (connected === ok) return;
  connected = ok;
  for (const cb of [...statusHandlers]) {
    try {
      cb(ok);
    } catch (err) {
      console.error("[WS] handler statut en erreur", err);
    }
  }
}

/** Parse un message brut et le dispatche aux handlers du champ "action". */
function dispatch(raw: string): void {
  let msg: WsMessage;
  try {
    msg = JSON.parse(raw) as WsMessage;
  } catch {
    return; // message malforme : on ignore sans crasher
  }
  const action = typeof msg.action === "string" ? msg.action : "";
  if (!action) return;
  const set = handlers.get(action);
  if (!set) return;
  for (const cb of [...set]) {
    try {
      cb(msg);
    } catch (err) {
      console.error(`[WS] handler "${action}" en erreur`, err);
    }
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_INTERVAL_MS);
}

/** Ouvre (ou rouvre) la connexion WebSocket. Idempotent. */
export function connect(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (
    socket &&
    (socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }
  try {
    socket = new WebSocket(WS_URL);
  } catch (err) {
    console.error("[WS] creation socket echouee", err);
    scheduleReconnect();
    return;
  }
  socket.addEventListener("open", () => notifyStatus(true));
  socket.addEventListener("message", (event: MessageEvent) =>
    dispatch(String(event.data))
  );
  socket.addEventListener("close", () => {
    notifyStatus(false);
    scheduleReconnect();
  });
  socket.addEventListener("error", () => notifyStatus(false));
}

/** Envoie un objet serialise en JSON. Retourne false si non connecte. */
export function send(obj: Record<string, unknown>): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  try {
    socket.send(JSON.stringify(obj));
    return true;
  } catch (err) {
    console.error("[WS] envoi echoue", err);
    return false;
  }
}

/** Abonne un handler a une action serveur. Retourne la fonction de desabonnement. */
export function on(action: string, cb: WsHandler): () => void {
  let set = handlers.get(action);
  if (!set) {
    set = new Set();
    handlers.set(action, set);
  }
  set.add(cb);
  return () => {
    set.delete(cb);
  };
}

/** Abonne un handler aux changements de statut. Retourne le desabonnement. */
export function onStatus(cb: StatusHandler): () => void {
  statusHandlers.add(cb);
  return () => {
    statusHandlers.delete(cb);
  };
}

/** Etat de connexion courant. */
export function isConnected(): boolean {
  return connected;
}
