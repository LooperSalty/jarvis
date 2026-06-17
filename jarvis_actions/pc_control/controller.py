"""Controleur : assemble le routeur et les capacites, expose le contrat main2.

`executer(texte) -> (str|None, bool)` : route le texte vers une intention, trouve
la capacite du domaine, la fait agir, et convertit le resultat. Deuxieme barriere
de fiabilite (try/except global) en plus du `never_throw` de chaque capacite.
"""

from __future__ import annotations

from jarvis_config import USER_NAME

from .core import ActionResult, get_logger
from .router import Router


class Controller:
    """Aiguille texte -> intention -> capacite -> ActionResult."""

    def __init__(self, router: Router, capabilities: dict, logger=None) -> None:
        self._router = router
        self._caps = capabilities  # dict[domaine -> Capability]
        self._log = logger or get_logger()

    @property
    def capabilities(self) -> dict:
        return self._caps

    def handle(self, texte: str) -> ActionResult:
        """Variante structuree (renvoie un ActionResult)."""
        try:
            intent = self._router.route(texte)
            if intent is None:
                return ActionResult.unhandled()
            cap = self._caps.get(intent.domaine)
            if cap is None:
                # Routeur a matche mais aucune capacite cablee : on log et on laisse
                # filer a l'IA plutot que de vocaliser une erreur deroutante.
                self._log.warning("[PCCTL] aucune capacite pour le domaine '%s'", intent.domaine)
                return ActionResult.unhandled()
            return cap.handle(intent)
        except Exception:  # noqa: BLE001 - 2e barriere : rien ne remonte a main2
            self._log.exception("[PCCTL] erreur inattendue dans le controleur")
            return ActionResult.fail(f"Une erreur interne est survenue, {USER_NAME}.")

    def executer(self, texte: str) -> tuple[str | None, bool]:
        """Contrat main2 : (reponse, succes) ou (None, False) si non gere."""
        return self.handle(texte).to_legacy()
