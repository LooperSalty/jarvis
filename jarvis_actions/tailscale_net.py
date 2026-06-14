"""Detection de l'acces Tailscale (IP du tailnet) pour piloter Jarvis a distance.

Jarvis sert deja l'interface mobile (HTTP :8080) et le WebSocket authentifie
(:8765). Sur le LAN, le telephone s'y connecte via l'IP locale. Avec Tailscale
(VPN maille), le telephone peut joindre le PC depuis N'IMPORTE OU, via une IP
stable du tailnet (plage CGNAT 100.64.0.0/10).

Ce module se contente de DETECTER l'IP Tailscale de la machine (il n'installe ni
ne configure rien) :
- d'abord via la CLI `tailscale ip -4` si elle est presente,
- sinon en repli, en scannant les interfaces reseau a la recherche d'une IP dans
  la plage CGNAT de Tailscale.

`_ip_dans_plage_tailscale` est une fonction PURE (testable sans reseau).
psutil est optionnel : son absence degrade proprement (-> pas de repli interface).
"""

from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess

# Plage CGNAT partagee utilisee par Tailscale pour les IP du tailnet.
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")

# Port de l'interface mobile servie par Jarvis (cf. serveur HTTP de main2).
PORT_MOBILE = 8080


def _ip_dans_plage_tailscale(ip: str) -> bool:
    """True si `ip` appartient a la plage CGNAT de Tailscale (100.64.0.0/10).

    Fonction PURE : aucune I/O. Toute entree invalide -> False (jamais d'exception).
    """
    try:
        return ipaddress.ip_address(ip) in _TAILSCALE_CGNAT
    except ValueError:
        return False


def _ip_via_cli() -> str:
    """IP Tailscale via `tailscale ip -4`. Renvoie "" si CLI absente ou erreur."""
    cli = shutil.which("tailscale")
    if not cli:
        return ""
    try:
        r = subprocess.run(
            [cli, "ip", "-4"],
            capture_output=True, text=True, timeout=4, shell=False,
        )
    except Exception:  # noqa: BLE001 - CLI capricieuse / timeout / droits
        return ""
    if r.returncode != 0:
        return ""
    for ligne in r.stdout.splitlines():
        ip = ligne.strip()
        if _ip_dans_plage_tailscale(ip):
            return ip
    return ""


def _ip_via_interfaces() -> str:
    """Repli : cherche une IP Tailscale parmi les interfaces reseau (besoin psutil)."""
    try:
        import psutil  # type: ignore
    except Exception:  # noqa: BLE001 - psutil optionnel
        return ""
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and _ip_dans_plage_tailscale(a.address):
                    return a.address
    except Exception:  # noqa: BLE001
        return ""
    return ""


def detecter_ip() -> str:
    """IP Tailscale de cette machine, ou "" si non detectee.

    Strategie : CLI `tailscale` d'abord (source de verite), repli sur le scan des
    interfaces (utile si la CLI n'est pas dans le PATH mais le service tourne).
    """
    return _ip_via_cli() or _ip_via_interfaces()


def statut(token: str = "", port_mobile: int = PORT_MOBILE) -> dict:
    """Statut Tailscale pour le dashboard.

    Retourne {actif, ip, url_mobile}. Si `token` est fourni, l'URL inclut le
    `?token=` qui appaire automatiquement le mobile. Sans IP : actif=False.
    """
    ip = detecter_ip()
    if not ip:
        return {"actif": False, "ip": "", "url_mobile": ""}
    base = f"http://{ip}:{port_mobile}"
    url = f"{base}/?token={token}" if token else base
    return {"actif": True, "ip": ip, "url_mobile": url}
