"""Pont vers le SDK OpenJarvis (Stanford SAIL) — utilise comme cerveau alternatif.

Active uniquement si la variable d'environnement USE_OPENJARVIS=1 est definie.
Sinon, ce module reste totalement passif et n'impacte rien.

Pourquoi ce pont ?
    OpenJarvis expose 14 backends d'inference (ollama, vllm, mlx, llamacpp, sglang,
    cloud OpenAI/Anthropic/Gemini, ...) derriere une API unique, plus de la
    telemetry, des security guardrails, une memoire indexable, et un registre
    d'agents. Ce wrapper permet a main2.py d'y deleguer la generation tout en
    gardant SON system prompt (jarvis francais, profil utilisateur, memoire Obsidian).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_INSTANCE: Optional["OpenJarvisBrain"] = None
_AVAILABLE: Optional[bool] = None


def is_enabled() -> bool:
    """Le pont est-il active par l'utilisateur ?"""
    return os.getenv("USE_OPENJARVIS", "").lower() in ("1", "true", "yes", "on") or is_agent_enabled()


def is_agent_enabled() -> bool:
    """Le mode agent (tool-calling) est-il active ? Implique is_enabled()."""
    return os.getenv("USE_OPENJARVIS_AGENT", "").lower() in ("1", "true", "yes", "on")


def is_available() -> bool:
    """OpenJarvis est-il importable ? (cache le resultat)."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        import openjarvis  # noqa: F401

        _AVAILABLE = True
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenJarvis non disponible: %s", exc)
        _AVAILABLE = False
    return _AVAILABLE


class OpenJarvisBrain:
    """Wrapper paresseux + thread-safe du SDK OpenJarvis."""

    def __init__(
        self,
        *,
        engine_key: Optional[str] = None,
        default_model: Optional[str] = None,
    ) -> None:
        from openjarvis import Jarvis

        self._jarvis = Jarvis(engine_key=engine_key, model=default_model)
        self._engine_key = engine_key
        self._default_model = default_model

    @classmethod
    def get(cls) -> "OpenJarvisBrain":
        """Singleton. Ne build que si USE_OPENJARVIS=1 et package installe."""
        global _INSTANCE
        if _INSTANCE is None:
            engine = os.getenv("OPENJARVIS_ENGINE") or None
            model = os.getenv("OPENJARVIS_MODEL") or None
            _INSTANCE = cls(engine_key=engine, default_model=model)
        return _INSTANCE

    @classmethod
    def reset(cls) -> None:
        """Force la reconstruction au prochain appel (utile pour tests)."""
        global _INSTANCE
        if _INSTANCE is not None:
            try:
                _INSTANCE._jarvis.close()
            except Exception:  # noqa: BLE001
                pass
        _INSTANCE = None

    def list_engines(self) -> List[str]:
        return self._jarvis.list_engines()

    def list_models(self) -> List[str]:
        try:
            return self._jarvis.list_models()
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_models a echoue: %s", exc)
            return []

    async def ask(
        self,
        texte: str,
        *,
        system_prompt: Optional[str] = None,
        history: Optional[List[Tuple[str, str]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """Genere une reponse complete (non-streaming) sans bloquer la loop asyncio.

        history : liste de tuples (role, content) avec role in {"user", "assistant"}.
        Renvoie None en cas d'echec total.
        """
        from openjarvis.core.types import Message, Role

        msgs: List[Message] = []
        if system_prompt:
            msgs.append(Message(role=Role.SYSTEM, content=system_prompt))
        for role, content in history or []:
            r = Role.USER if role == "user" else Role.ASSISTANT
            msgs.append(Message(role=r, content=content))
        msgs.append(Message(role=Role.USER, content=texte))

        def _run() -> Optional[str]:
            try:
                self._jarvis._ensure_engine()  # type: ignore[attr-defined]
                model_name = (
                    model
                    or self._default_model
                    or self._jarvis.config.intelligence.default_model
                    or (self._jarvis.list_models() or ["default"])[0]
                )
                result = self._jarvis._engine.generate(  # type: ignore[attr-defined]
                    msgs,
                    model=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if isinstance(result, dict):
                    return result.get("content", "") or None
                return str(result) or None
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenJarvis ask a echoue: %s", exc)
                return None

        return await asyncio.to_thread(_run)

    async def ask_agent(
        self,
        texte: str,
        *,
        agent_name: str = "orchestrator",
        system_prompt: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        max_turns: int = 6,
    ) -> Optional[dict]:
        """Lance un agent OpenJarvis (tool-calling) avec les tools enregistres.

        Renvoie un dict {content, tool_results, turns} ou None si echec.
        """
        try:
            # Trigger registration
            from jarvis_actions import openjarvis_tools as _tools

            _tools.register_jarvis_tools()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Echec register_jarvis_tools: %s", exc)

        def _run() -> Optional[dict]:
            try:
                import openjarvis.agents  # noqa: F401
                from openjarvis.agents._stubs import AgentContext
                from openjarvis.core.registry import AgentRegistry, ToolRegistry
                from openjarvis.tools._stubs import BaseTool

                if not AgentRegistry.contains(agent_name):
                    logger.warning("agent inconnu: %s", agent_name)
                    return None

                self._jarvis._ensure_engine()  # type: ignore[attr-defined]
                model_name = (
                    model
                    or self._default_model
                    or self._jarvis.config.intelligence.default_model
                    or (self._jarvis.list_models() or ["default"])[0]
                )

                names = tool_names or [
                    "meross_light",
                    "open_app",
                    "system_volume",
                    "open_vscode_project",
                    "git_status",
                    "obsidian_note",
                    "obsidian_remember",
                ]
                tool_objs: List[BaseTool] = []
                for n in names:
                    if not ToolRegistry.contains(n):
                        continue
                    cls = ToolRegistry.get(n)
                    if isinstance(cls, type) and issubclass(cls, BaseTool):
                        tool_objs.append(cls())
                    elif isinstance(cls, BaseTool):
                        tool_objs.append(cls)

                agent_cls = AgentRegistry.get(agent_name)
                agent_kwargs = {
                    "bus": self._jarvis._bus,  # type: ignore[attr-defined]
                    "tools": tool_objs,
                    "max_turns": max_turns,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if system_prompt and agent_name == "orchestrator":
                    agent_kwargs["system_prompt"] = system_prompt

                agent = agent_cls(self._jarvis._engine, model_name, **agent_kwargs)  # type: ignore[attr-defined]
                ctx = AgentContext()
                result = agent.run(texte, context=ctx)
                return {
                    "content": result.content,
                    "turns": result.turns,
                    "tool_results": [
                        {
                            "tool_name": tr.tool_name,
                            "content": tr.content,
                            "success": tr.success,
                        }
                        for tr in result.tool_results
                    ],
                    "model": model_name,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("ask_agent a echoue: %s", exc)
                return None

        return await asyncio.to_thread(_run)

    async def stream(
        self,
        texte: str,
        *,
        system_prompt: Optional[str] = None,
        history: Optional[List[Tuple[str, str]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streame la reponse token par token."""
        from openjarvis.core.types import Message, Role

        msgs: List[Message] = []
        if system_prompt:
            msgs.append(Message(role=Role.SYSTEM, content=system_prompt))
        for role, content in history or []:
            r = Role.USER if role == "user" else Role.ASSISTANT
            msgs.append(Message(role=r, content=content))
        msgs.append(Message(role=Role.USER, content=texte))

        try:
            self._jarvis._ensure_engine()  # type: ignore[attr-defined]
            model_name = (
                model
                or self._default_model
                or self._jarvis.config.intelligence.default_model
                or (self._jarvis.list_models() or ["default"])[0]
            )
            async for token in self._jarvis._engine.stream(  # type: ignore[attr-defined]
                msgs,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if token:
                    yield token
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenJarvis stream a echoue: %s", exc)
            return


def maybe_brain() -> Optional[OpenJarvisBrain]:
    """Retourne l'instance OpenJarvisBrain seulement si activee + dispo."""
    if not is_enabled():
        return None
    if not is_available():
        return None
    try:
        return OpenJarvisBrain.get()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenJarvis init a echoue: %s", exc)
        return None


# Helpers pour main2.py (style sync wrappers utiles)
async def ask_with_history_async(
    texte: str,
    *,
    system_prompt: str,
    history_pairs: List[Tuple[str, str]],
) -> Optional[str]:
    """Helper haut-niveau pour main2.demander_ia : essaie OpenJarvis, fallback None."""
    brain = maybe_brain()
    if brain is None:
        return None
    return await brain.ask(
        texte, system_prompt=system_prompt, history=history_pairs
    )


async def ask_agent_async(
    texte: str,
    *,
    system_prompt: str,
) -> Optional[dict]:
    """Helper agent (tool-calling). Active si USE_OPENJARVIS_AGENT=1."""
    if not is_agent_enabled():
        return None
    brain = maybe_brain()
    if brain is None:
        return None
    return await brain.ask_agent(texte, system_prompt=system_prompt)


async def stream_with_history_async(
    texte: str,
    *,
    system_prompt: str,
    history_pairs: List[Tuple[str, str]],
) -> AsyncIterator[str]:
    """Helper streaming pour main2.demander_ollama_stream."""
    brain = maybe_brain()
    if brain is None:
        return
    async for token in brain.stream(
        texte, system_prompt=system_prompt, history=history_pairs
    ):
        yield token


def history_to_pairs(historique_gemini: List[Any], limit: int = 6) -> List[Tuple[str, str]]:
    """Convertit l'historique Gemini de main2 en liste (role, content)."""
    out: List[Tuple[str, str]] = []
    for h in historique_gemini[-limit:]:
        try:
            role = "user" if h.role == "user" else "assistant"
            content = h.parts[0].text
            if content:
                out.append((role, content))
        except (AttributeError, IndexError):
            continue
    return out


__all__ = [
    "OpenJarvisBrain",
    "is_enabled",
    "is_agent_enabled",
    "is_available",
    "maybe_brain",
    "ask_with_history_async",
    "ask_agent_async",
    "stream_with_history_async",
    "history_to_pairs",
]
