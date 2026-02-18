"""
Memory management system for CapivaraX Bot.

Handles:
- Notes storage and retrieval
- User preferences
- Memory persistence
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("unbx_bot.memory")

DEFAULT_ENCODING = "utf-8"


class MemoryManager:
    """Manages bot memory (notes and preferences)."""

    def __init__(self, workspace_dir: Path):
        self.workspace = workspace_dir
        self.memory_file = workspace_dir / "memoria.json"
        self.notes_export_file = workspace_dir / "notas_export.md"

        # Ensure workspace exists
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.default_memory = {
            "notas": [],
            "preferencias": {
                "formato": "topicos",
                "tamanho": "curto",
                "tom": "descontraido"
            }
        }

    def load(self) -> Dict:
        """Load memory from file."""
        if not self.memory_file.exists():
            self.save(self.default_memory)
            return self.default_memory.copy()

        try:
            with open(self.memory_file, 'r', encoding=DEFAULT_ENCODING) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load memory: {e}")
            return self.default_memory.copy()

    def save(self, memory: Dict):
        """Save memory to file."""
        try:
            with open(self.memory_file, 'w', encoding=DEFAULT_ENCODING) as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def add_note(self, content: str) -> bool:
        """Add a new note to memory."""
        try:
            mem = self.load()
            note = {
                "id": len(mem["notas"]) + 1,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "tags": []
            }
            mem["notas"].append(note)
            self.save(mem)
            return True
        except Exception as e:
            logger.error(f"Failed to add note: {e}")
            return False

    def get_notes(self, limit: Optional[int] = None) -> List[Dict]:
        """Get all notes (or limited number)."""
        mem = self.load()
        notes = mem.get("notas", [])

        if limit:
            return notes[-limit:]
        return notes

    def search_notes(self, query: str) -> List[Dict]:
        """Search notes by content."""
        mem = self.load()
        notes = mem.get("notas", [])
        query_lower = query.lower()

        return [
            note for note in notes
            if query_lower in note.get("content", "").lower()
        ]

    def delete_note(self, note_id: int) -> bool:
        """Delete a note by ID."""
        try:
            mem = self.load()
            notes = mem.get("notas", [])
            mem["notas"] = [n for n in notes if n.get("id") != note_id]
            self.save(mem)
            return True
        except Exception as e:
            logger.error(f"Failed to delete note: {e}")
            return False

    def clear_all_notes(self) -> bool:
        """Clear all notes."""
        try:
            mem = self.load()
            mem["notas"] = []
            self.save(mem)
            return True
        except Exception as e:
            logger.error(f"Failed to clear notes: {e}")
            return False

    def export_notes_to_markdown(self) -> str:
        """Export all notes to markdown file."""
        mem = self.load()
        notes = mem.get("notas", [])

        if not notes:
            return "Nenhuma nota para exportar."

        lines = [
            "# 📝 Notas Exportadas",
            "",
            f"**Data de exportação:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total de notas:** {len(notes)}",
            "",
            "---",
            ""
        ]

        for note in notes:
            note_id = note.get("id", "?")
            content = note.get("content", "")
            timestamp = note.get("timestamp", "")

            lines.append(f"## Nota #{note_id}")
            lines.append(f"**Data:** {timestamp}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        markdown_content = "\n".join(lines)

        try:
            with open(self.notes_export_file, 'w', encoding=DEFAULT_ENCODING) as f:
                f.write(markdown_content)
            return str(self.notes_export_file)
        except Exception as e:
            logger.error(f"Failed to export notes: {e}")
            return f"Erro ao exportar: {e}"

    def get_preferences(self) -> Dict:
        """Get user preferences."""
        mem = self.load()
        return mem.get("preferencias", self.default_memory["preferencias"])

    def update_preferences(self, preferences: Dict):
        """Update user preferences."""
        mem = self.load()
        mem["preferencias"].update(preferences)
        self.save(mem)

    def get_context_for_ai(self) -> str:
        """Get memory context formatted for AI."""
        mem = self.load()
        notes = mem.get("notas", [])
        prefs = mem.get("preferencias", {})

        context_parts = []

        # Add preferences
        if prefs:
            context_parts.append("**Preferências do usuário:**")
            for key, value in prefs.items():
                context_parts.append(f"- {key}: {value}")
            context_parts.append("")

        # Add recent notes
        if notes:
            recent_notes = notes[-5:]  # Last 5 notes
            context_parts.append("**Notas recentes:**")
            for note in recent_notes:
                content = note.get("content", "")[:100]  # First 100 chars
                context_parts.append(f"- {content}...")
            context_parts.append("")

        return "\n".join(context_parts) if context_parts else ""
