"""Pont entre la memoire de Jarvis et un vault Obsidian.

Chaque memoire devient un fichier markdown dans `{vault}/Jarvis/Memoire/`.
Les conversations sont consignees dans `{vault}/Jarvis/Conversations/{YYYY-MM-DD}.md`.
"""

from __future__ import annotations

import re
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable
from jarvis_config import USER_NAME


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slugify(value: str) -> str:
    s = value.lower().strip()
    s = s.replace(" ", "-")
    s = _SLUG_RE.sub("", s)
    return s[:80] or "note"


class ObsidianBridge:
    def __init__(self, vault_path: str):
        self.vault = Path(vault_path).expanduser()
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault Obsidian introuvable : {self.vault}")
        self.root = self.vault / "Jarvis"
        self.dir_memoire = self.root / "Memoire"
        self.dir_conversations = self.root / "Conversations"
        self.dir_notes = self.root / "Notes"
        for d in (self.root, self.dir_memoire, self.dir_conversations, self.dir_notes):
            d.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    def _ensure_index(self) -> None:
        idx = self.root / "README.md"
        if idx.exists():
            return
        idx.write_text(
            "# Jarvis\n\n"
            "Cet espace est gere automatiquement par Jarvis.\n\n"
            "- `Memoire/` : faits persistants connus de Jarvis (1 fichier par cle)\n"
            "- `Conversations/` : transcriptions des echanges, un fichier par jour\n"
            "- `Notes/` : notes libres ecrites par toi ou par Jarvis\n\n"
            "Tu peux modifier ces fichiers directement, Jarvis recharge la memoire au boot.\n",
            encoding="utf-8",
        )

    def save_memory(self, key: str, value: str, timestamp: str | None = None) -> Path:
        ts = timestamp or datetime.now().strftime("%d/%m/%Y %H:%M")
        slug = _slugify(key)
        path = self.dir_memoire / f"{slug}.md"
        body = (
            f"---\n"
            f"key: {json.dumps(key, ensure_ascii=False)}\n"
            f"timestamp: {json.dumps(ts, ensure_ascii=False)}\n"
            f"updated: {datetime.now().isoformat(timespec='seconds')}\n"
            f"---\n\n"
            f"# {key}\n\n"
            f"{value}\n"
        )
        path.write_text(body, encoding="utf-8")
        return path

    def delete_memory(self, key: str) -> bool:
        slug = _slugify(key)
        path = self.dir_memoire / f"{slug}.md"
        if path.exists():
            path.unlink()
            return True
        return False

    def load_all_memories(self) -> dict[str, dict[str, str]]:
        memories: dict[str, dict[str, str]] = {}
        for path in self.dir_memoire.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
                key = self._extract_frontmatter_field(text, "key") or path.stem
                ts = self._extract_frontmatter_field(text, "timestamp") or ""
                value = self._extract_body(text).strip()
                if value:
                    memories[key] = {"valeur": value, "timestamp": ts}
            except Exception:
                continue
        return memories

    @staticmethod
    def _extract_frontmatter_field(text: str, field: str) -> str | None:
        if not text.startswith("---"):
            return None
        end = text.find("\n---", 3)
        if end == -1:
            return None
        block = text[3:end]
        for line in block.splitlines():
            if line.startswith(f"{field}:"):
                raw = line.split(":", 1)[1].strip()
                if raw.startswith('"') and raw.endswith('"'):
                    try:
                        return json.loads(raw)
                    except Exception:
                        return raw.strip('"')
                return raw
        return None

    @staticmethod
    def _extract_body(text: str) -> str:
        if not text.startswith("---"):
            return text
        end = text.find("\n---", 3)
        if end == -1:
            return text
        body = text[end + 4 :].lstrip()
        body = re.sub(r"^#\s+.+?\n", "", body, count=1)
        return body

    def append_conversation(self, role: str, content: str) -> None:
        if not content.strip():
            return
        day = datetime.now().strftime("%Y-%m-%d")
        path = self.dir_conversations / f"{day}.md"
        if not path.exists():
            path.write_text(
                f"---\ndate: {day}\n---\n\n# Conversations du {day}\n\n",
                encoding="utf-8",
            )
        time_str = datetime.now().strftime("%H:%M:%S")
        speaker = f"{USER_NAME}" if role == "user" else "Jarvis"
        line = f"**[{time_str}] {speaker}** : {content.strip()}\n\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def save_note(self, title: str, content: str) -> Path:
        slug = _slugify(title)
        path = self.dir_notes / f"{slug}.md"
        path.write_text(
            f"---\ntitle: {json.dumps(title, ensure_ascii=False)}\n"
            f"created: {datetime.now().isoformat(timespec='seconds')}\n---\n\n"
            f"# {title}\n\n{content}\n",
            encoding="utf-8",
        )
        return path


def auto_detect_vault() -> str | None:
    candidats: Iterable[Path] = [
        Path(os.path.expanduser("~/Documents/Obsidian Vault")),
        Path(os.path.expanduser("~/OneDrive/Documents/Obsidian Vault")),
        Path(os.path.expanduser("~/Obsidian")),
    ]
    for c in candidats:
        if (c / ".obsidian").exists():
            return str(c)
    return None
