"""Source scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from backend.app.parsers.base import SourceFile


EXTENSION_LANGUAGE = {
    ".vue": "frontend",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".jsp": "jsp",
    ".html": "html",
    ".java": "java",
    ".xml": "xml",
    ".sql": "sql",
    ".md": "markdown",
    ".csv": "csv",
    ".xlsx": "xlsx",
}
IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}


class SourceScanner:
    """Scan source directories for supported file types."""

    def scan(self, source_dir: str) -> List[SourceFile]:
        """Return loaded source files."""
        root = Path(source_dir)
        files: List[SourceFile] = []
        for path in self._iter_files(root):
            suffix = path.suffix.lower()
            language = EXTENSION_LANGUAGE.get(suffix)
            if not language:
                continue
            if suffix == ".xlsx":
                text = ""
            else:
                text = path.read_text(encoding="utf-8")
            files.append(SourceFile(path=path, language=language, text=text))
        return files

    def _iter_files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*")):
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path
