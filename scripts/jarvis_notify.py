"""Petit utilitaire pour envoyer un message a Jarvis depuis n'importe quel script.

Usage :
    python jarvis_notify.py "Ton message a vocaliser"
    python jarvis_notify.py --type cmd "ouvre chrome"
    python jarvis_notify.py --type tell "Claude Code vient de finir une tache"
"""

import argparse
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("[NOTIFY] websockets non installe : python -m pip install websockets", file=sys.stderr)
    sys.exit(1)

WS_URL = "ws://localhost:8765"


async def send(payload: dict, timeout: float = 4.0) -> None:
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(WS_URL) as ws:
                await ws.send(json.dumps(payload))
    except Exception as e:
        print(f"[NOTIFY] Echec envoi a Jarvis : {e}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envoie un message a Jarvis.")
    parser.add_argument("message", help="Texte a transmettre.")
    parser.add_argument(
        "--type",
        choices=["tell", "cmd"],
        default="tell",
        help="'tell' = Jarvis vocalise le texte ; 'cmd' = traite comme une commande utilisateur.",
    )
    args = parser.parse_args()

    if args.type == "tell":
        payload = {"type": "external_say", "text": args.message}
    else:
        payload = {"type": "text_command", "text": args.message}

    asyncio.run(send(payload))


if __name__ == "__main__":
    main()
