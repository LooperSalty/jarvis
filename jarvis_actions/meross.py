"""Controle des prises Meross (Wi-Fi switches MSS710 etc.) via le cloud Meross.

Detection mots-cles : "allume/eteins la lumiere/lampe/prise" -> ON/OFF.

Pre-requis :
- pip install meross_iot
- .env : MEROSS_EMAIL=... MEROSS_PASSWORD=...
- Optionnel : MEROSS_API_BASE (defaut https://iotx-eu.meross.com pour l'Europe ;
  https://iotx-us.meross.com pour les US, https://iotx-ap.meross.com pour l'Asie)

Le manager est cache au premier appel (login une seule fois) puis reutilise.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import threading
from jarvis_config import USER_NAME

# Lazy import (meross_iot peut etre absent dans certains setups)
_MANAGER = None
_HTTP_CLIENT = None
_INIT_LOCK: asyncio.Lock | None = None  # cree dans le loop dedie

# Thread + event loop dedies pour Meross : la connexion MQTT a des callbacks
# qui se referent au loop d'origine. En isolant Meross dans son propre thread,
# le loop ne change jamais et on evite "Future attached to different loop".
_MEROSS_LOOP: asyncio.AbstractEventLoop | None = None
_MEROSS_THREAD: threading.Thread | None = None
_THREAD_LOCK = threading.Lock()


def _ensure_meross_thread() -> asyncio.AbstractEventLoop:
    """Lance (une fois) le thread+loop dedie a Meross. Retourne le loop."""
    global _MEROSS_LOOP, _MEROSS_THREAD
    with _THREAD_LOCK:
        if _MEROSS_THREAD and _MEROSS_THREAD.is_alive():
            return _MEROSS_LOOP
        _MEROSS_LOOP = asyncio.new_event_loop()
        def _runner(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        _MEROSS_THREAD = threading.Thread(
            target=_runner, args=(_MEROSS_LOOP,),
            daemon=True, name="meross-worker",
        )
        _MEROSS_THREAD.start()
        return _MEROSS_LOOP


async def _run_in_meross_loop(coro):
    """Execute coro dans le loop dedie Meross, retourne son resultat
    (peut etre awaite depuis n'importe quel autre loop)."""
    loop = _ensure_meross_thread()
    cf = asyncio.run_coroutine_threadsafe(coro, loop)
    return await asyncio.wrap_future(cf)


async def _ensure_manager_internal():
    """A executer SEULEMENT dans le loop Meross dedie."""
    global _MANAGER, _HTTP_CLIENT, _INIT_LOCK
    if _INIT_LOCK is None:
        _INIT_LOCK = asyncio.Lock()
    if _MANAGER is not None:
        return _MANAGER

    async with _INIT_LOCK:
        if _MANAGER is not None:
            return _MANAGER

        email = os.getenv("MEROSS_EMAIL")
        password = os.getenv("MEROSS_PASSWORD")
        if not email or not password:
            raise RuntimeError(
                "MEROSS_EMAIL ou MEROSS_PASSWORD manquant dans .env "
                "(ajoute tes identifiants Meross)"
            )

        from meross_iot.http_api import MerossHttpClient
        from meross_iot.manager import MerossManager

        api_base = os.getenv("MEROSS_API_BASE", "https://iotx-eu.meross.com")
        _HTTP_CLIENT = await MerossHttpClient.async_from_user_password(
            api_base_url=api_base, email=email, password=password,
        )
        mgr = MerossManager(http_client=_HTTP_CLIENT)
        await mgr.async_init()
        await mgr.async_device_discovery()
        _MANAGER = mgr
        devices = mgr.find_devices()
        print(f"[MEROSS] Connecte. {len(devices)} appareil(s) detecte(s) : "
              f"{[d.name for d in devices]}")
    return _MANAGER


async def _ensure_manager():
    """Wrapper public qui execute dans le loop Meross dedie."""
    return await _run_in_meross_loop(_ensure_manager_internal())


async def _switch_internal(target_on: bool, name_filter: str | None = None) -> tuple[bool, str]:
    """Logique pure — A EXECUTER DANS LE LOOP MEROSS UNIQUEMENT."""
    mgr = await _ensure_manager_internal()
    devices = mgr.find_devices()
    if name_filter:
        nf = name_filter.lower()
        devices = [d for d in devices if nf in (d.name or "").lower()]
    if not devices:
        return False, "Aucune prise Meross trouvee"

    n_ok = 0
    for d in devices:
        try:
            await d.async_update()
            if target_on:
                await d.async_turn_on(channel=0)
            else:
                await d.async_turn_off(channel=0)
            n_ok += 1
        except Exception as e:
            print(f"[MEROSS] Echec sur {d.name}: {e}")
    label = "allumee" if target_on else "eteinte"
    plur = "s" if n_ok > 1 else ""
    return n_ok > 0, f"{n_ok} prise{plur} {label}{plur}"


async def _toggle_internal(name_filter: str | None = None) -> tuple[bool, str]:
    """Logique pure — A EXECUTER DANS LE LOOP MEROSS UNIQUEMENT."""
    mgr = await _ensure_manager_internal()
    devices = mgr.find_devices()
    if name_filter:
        nf = name_filter.lower()
        devices = [d for d in devices if nf in (d.name or "").lower()]
    if not devices:
        return False, "Aucune prise Meross trouvee"

    n_on, n_off = 0, 0
    for d in devices:
        try:
            await d.async_update()
            currently_on = d.is_on(channel=0)
            if currently_on:
                await d.async_turn_off(channel=0)
                n_off += 1
            else:
                await d.async_turn_on(channel=0)
                n_on += 1
        except Exception as e:
            print(f"[MEROSS] Echec toggle sur {d.name}: {e}")

    if n_on and not n_off:
        return True, f"{n_on} prise(s) allumee(s)"
    if n_off and not n_on:
        return True, f"{n_off} prise(s) eteinte(s)"
    if n_on and n_off:
        return True, f"{n_on} allumee(s), {n_off} eteinte(s)"
    return False, "Aucune prise n'a pu etre togglee"


async def _switch(target_on: bool, name_filter: str | None = None) -> tuple[bool, str]:
    """Wrapper public : delegue au loop Meross dedie."""
    return await _run_in_meross_loop(_switch_internal(target_on, name_filter))


async def _toggle(name_filter: str | None = None) -> tuple[bool, str]:
    """Wrapper public : delegue au loop Meross dedie."""
    return await _run_in_meross_loop(_toggle_internal(name_filter))


async def shutdown():
    """Ferme proprement le manager et le client HTTP (a appeler au quit)."""
    global _MANAGER, _HTTP_CLIENT
    try:
        if _MANAGER is not None:
            _MANAGER.close()
    except Exception:
        pass
    try:
        if _HTTP_CLIENT is not None:
            await _HTTP_CLIENT.async_logout()
    except Exception:
        pass
    _MANAGER = None
    _HTTP_CLIENT = None


# ============================================================
# Detection mots-cles + executer
# ============================================================

# Mots designant l'objet a controler
_TARGET = r"(?:lumi[èe]re|lampe|prise|switch|spot|loupiote)"

# Verbes ON / OFF (alternatives consolidees, plus de doublons)
_RE_ALLUMER = re.compile(
    rf"\b(?:allume[rsz]?|allum[ée]e?s?|on)\b.*?\b{_TARGET}\b",
    re.IGNORECASE,
)
_RE_ETEINDRE = re.compile(
    rf"\b(?:[ée]tein[tds]?|[ée]teindre|[ée]teignez|coupe[rsz]?|stoppe?|off)\b.*?\b{_TARGET}\b",
    re.IGNORECASE,
)
# TOGGLE : juste le mot "lumiere" / "lampe" tout seul (sans verbe)
# -> bascule selon l'etat actuel du switch
_RE_TOGGLE = re.compile(rf"\b{_TARGET}\b", re.IGNORECASE)


async def async_executer(texte: str) -> tuple[str | None, bool]:
    """Detecte une commande Meross dans le texte. Renvoie (reponse, success).
    (None, False) si rien ne matche -> laisse les autres modules gerer.

    Ordre des tests :
    1. ALLUMER explicite -> ON
    2. ETEINDRE explicite -> OFF
    3. juste "lumiere" / "lampe" tout seul -> TOGGLE selon l'etat actuel
    """
    if _RE_ALLUMER.search(texte):
        try:
            ok, msg = await _switch(target_on=True)
            return (f"Lumiere allumee, {USER_NAME}." if ok else f"Probleme : {msg}"), ok
        except Exception as e:
            return f"Erreur Meross : {e}", False

    if _RE_ETEINDRE.search(texte):
        try:
            ok, msg = await _switch(target_on=False)
            return (f"Lumiere eteinte, {USER_NAME}." if ok else f"Probleme : {msg}"), ok
        except Exception as e:
            return f"Erreur Meross : {e}", False

    # Toggle : commande comme "lumiere", "la lampe", "jarvis lumiere" etc.
    if _RE_TOGGLE.search(texte):
        try:
            ok, msg = await _toggle()
            if not ok:
                return f"Probleme : {msg}", False
            # Reponse vocale qui indique le nouvel etat
            if "allumee" in msg:
                return f"Lumiere allumee, {USER_NAME}.", True
            if "eteinte" in msg:
                return f"Lumiere eteinte, {USER_NAME}.", True
            return msg, True
        except Exception as e:
            return f"Erreur Meross : {e}", False

    return None, False
