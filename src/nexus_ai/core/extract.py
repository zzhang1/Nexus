from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractResult:
    text: str
    kind: str


def extract_text(path: Path) -> ExtractResult:
    ext = path.suffix.lower()
    if ext in {".md", ".markdown", ".txt"}:
        return ExtractResult(text=path.read_text(encoding="utf-8", errors="replace"), kind=ext.lstrip("."))

    if ext == ".pdf":
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return ExtractResult(text="\n\n".join(p for p in parts if p.strip()), kind="pdf")

    if ext == ".docx":
        doc = DocxDocument(str(path))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        return ExtractResult(text="\n\n".join(parts), kind="docx")

    # Fallback: best-effort text decode
    data = path.read_bytes()
    return ExtractResult(text=data.decode("utf-8", errors="replace"), kind="binary")

