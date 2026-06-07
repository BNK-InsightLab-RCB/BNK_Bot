"""Structure-based chunking of parsed Markdown (deterministic, no LLM).

Design = general core + swappable domain profile.

- **General core**: parse the Markdown our parser emits (``<!-- page N -->``
  markers, GitHub-style tables, free text) into blocks, then group them into
  chunks. Tables are kept whole (never split mid-row), free text is grouped by
  section and split only when too long. Every chunk gets a context header
  (product · category/doc_type · section) prepended so the embedding carries
  the context that the raw cell text lacks (e.g. ``| 양도 | 불가 |`` does not
  say *which* product).
- **Domain profile**: the only domain-coupled part — how to read a product name
  from a filename, how to recognise a section header, how to split legal prose
  by article (제N조). Swap the profile for other document families.

sLLM (Qwen) is intentionally NOT used here. Each chunk reserves an empty
``context`` field so an LLM pass can later fill contextual summaries without
touching the verbatim body.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _nfc(s: str) -> str:
    """Normalise to NFC. macOS filenames/paths come as NFD (decomposed Hangul),
    which looks identical but breaks exact-match filters in Qdrant. Normalise
    all stored strings so payload values, headers and queries compare equal."""
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


# --------------------------------------------------------------------------- #
# Block model
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    page: int
    kind: str  # "table" | "text"
    text: str


_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def parse_blocks(md: str) -> list[Block]:
    """Split Markdown into page-tagged table/text blocks (blank-line separated)."""
    blocks: list[Block] = []
    page = 1
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        is_table = buf[0].lstrip().startswith("|")
        blocks.append(Block(page, "table" if is_table else "text", "\n".join(buf)))
        buf.clear()

    # TODO(fallback-cleanup): The Docling fallback path can emit content-less
    # placeholders like ``<!-- image -->`` that would currently leak into a text
    # chunk as noise. The lattice path (current docs) emits none, so this is not
    # an issue yet. When we actually process fallback (scanned / non-ruled) docs,
    # strip ONLY exact-match known-empty placeholders (allowlist, not a broad
    # regex) and assert content-char conservation so no real data is dropped.
    for line in md.splitlines():
        m = _PAGE_RE.match(line.strip())
        if m:
            flush()
            page = int(m.group(1))
            continue
        if line.strip() == "":
            flush()
            continue
        buf.append(line)
    flush()
    return blocks


def table_rows(table_md: str) -> list[list[str]]:
    """Parse a Markdown table block into rows (separator lines dropped)."""
    rows: list[list[str]] = []
    for line in table_md.splitlines():
        s = line.strip()
        if not s.startswith("|") or _TABLE_SEP_RE.match(s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    return rows


# --------------------------------------------------------------------------- #
# Domain profile (the only domain-coupled part)
# --------------------------------------------------------------------------- #
@dataclass
class DocProfile:
    """Base profile. Override the hooks for other document families."""

    name: str = "generic"
    _DOC_TYPE_WORDS = ("상품설명서", "설명서", "특약", "집합투자규약", "신탁계약서", "약관", "규약")

    def product_name(self, source_stem: str) -> str:
        s = re.sub(r"\[[^\]]*\]", "", source_stem)          # drop [부산은행] etc.
        # drop leading list-number prefix "14.", "6.", "403164_" — but the
        # lookahead (?=\D) keeps decimal product names like "3.6%정기예금" intact
        # (the char after the separator must be a non-digit).
        s = re.sub(r"^\s*\d+\s*[._]\s*(?=\D)", "", s)
        for w in self._DOC_TYPE_WORDS:                       # cut at doc-type word
            if w in s:
                s = s.split(w)[0]
                break
        s = re.sub(r"\([^)]*\)", "", s)                      # drop (date)/(ver)
        s = re.sub(r"[_\s]+", " ", s).strip(" _-")
        s = re.sub(r"\s*\d{4,6}\s*심의\s*$", "", s).strip()  # drop trailing "YYYYMM 심의"
        return s or source_stem

    def section_title(self, block: "Block") -> str | None:
        """A section header renders as a 1-row, 2-col table whose first cell is
        a number (e.g. ``| 2 | 거래 조건 |``)."""
        if block.kind != "table":
            return None
        rows = table_rows(block.text)
        if len(rows) == 1 and len(rows[0]) == 2 and re.fullmatch(r"\d+", rows[0][0]):
            return rows[0][1].strip()
        return None

    def split_long_text(self, text: str, max_chars: int) -> list[str]:
        """Split overly-long prose. Legal docs override to split by 제N조."""
        return _greedy_split(re.split(r"(?<=다\.)\s+|\n", text), max_chars)


class KoreanFinanceProfile(DocProfile):
    name = "korean_finance"
    _ARTICLE_RE = re.compile(r"(?=제\s*\d+\s*조)")

    def split_long_text(self, text: str, max_chars: int) -> list[str]:
        # Prefer article boundaries (제N조); fall back to sentence split.
        parts = [p for p in self._ARTICLE_RE.split(text) if p.strip()]
        if len(parts) > 1:
            return _greedy_split(parts, max_chars)
        return super().split_long_text(text, max_chars)


def _greedy_split(pieces: list[str], max_chars: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if cur and len(cur) + len(p) + 1 > max_chars:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out or [""]


# --------------------------------------------------------------------------- #
# Chunk model
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    text: str               # context header + body (this is what gets embedded)
    body: str               # verbatim body only
    product_name: str
    category: str           # 예금 | 펀드
    doc_type: str           # 설명서 | 약관 ...
    source_file: str
    page: int
    section: str
    kind: str               # "table" | "text"
    chunk_index: int
    context: str = ""        # reserved for later sLLM contextual summary
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Chunking core
# --------------------------------------------------------------------------- #
def _context_header(product: str, category: str, doc_type: str, section: str) -> str:
    head = f"[{product}]"
    if category or doc_type:
        head += f" · {category}/{doc_type}".rstrip("/")
    if section:
        head += f" · {section}"
    return head


def chunk_markdown(
    md: str,
    *,
    source_file: str,
    category: str = "",
    doc_type: str = "",
    product_name: str | None = None,
    profile: DocProfile | None = None,
    max_chars: int = 1500,
) -> list[Chunk]:
    profile = profile or KoreanFinanceProfile()
    # NB: do NOT use Path(...).stem here — filenames carry dots (dates like
    # "(2026.01.23)…", leading "6.BNK…") that Path mistakes for an extension and
    # truncates ("(2026.01", "6"). Strip only real .pdf/.md suffixes.
    stem = Path(source_file).name
    for ext in (".pdf", ".PDF", ".md"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    product = _nfc(product_name or profile.product_name(stem))
    category = _nfc(category)
    doc_type = _nfc(doc_type)
    source_name = _nfc(Path(source_file).name)

    blocks = parse_blocks(md)
    chunks: list[Chunk] = []
    section = ""
    text_buf: list[str] = []
    text_page = 1

    def emit(body: str, page: int, kind: str) -> None:
        body = _nfc(body.strip())
        if not body:
            return
        header = _context_header(product, category, doc_type, section)
        chunks.append(
            Chunk(
                text=f"{header}\n{body}",
                body=body,
                product_name=product,
                category=category,
                doc_type=doc_type,
                source_file=source_name,
                page=page,
                section=section,
                kind=kind,
                chunk_index=len(chunks),
            )
        )

    def flush_text() -> None:
        if not text_buf:
            return
        joined = "\n".join(text_buf)
        pieces = [joined] if len(joined) <= max_chars else profile.split_long_text(joined, max_chars)
        for p in pieces:
            emit(p, text_page, "text")
        text_buf.clear()

    for b in blocks:
        title = profile.section_title(b)
        if title is not None:           # section header -> set context, not a chunk
            flush_text()
            section = _nfc(title)
            continue
        if b.kind == "table":
            flush_text()
            emit(b.text, b.page, "table")   # tables kept whole
        else:
            if not text_buf:
                text_page = b.page
            text_buf.append(b.text)
    flush_text()
    return chunks


# --------------------------------------------------------------------------- #
# File convenience
# --------------------------------------------------------------------------- #
def chunk_md_file(
    md_path: str | Path,
    *,
    category: str = "",
    doc_type: str = "",
    profile: DocProfile | None = None,
    max_chars: int = 1500,
) -> list[Chunk]:
    md_path = Path(md_path)
    md = md_path.read_text(encoding="utf-8")
    return chunk_markdown(
        md,
        source_file=md_path.stem,
        category=category,
        doc_type=doc_type,
        profile=profile,
        max_chars=max_chars,
    )


def write_chunks(chunks: list[Chunk], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    return out_path


if __name__ == "__main__":
    import sys

    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.config import settings

    stem = "[부산은행]마이플랜퇴직연금정기예금_상품설명서(2025.12.01)(4)"
    md_file = settings.processed_dir / stem / f"{stem}.md"
    # category/doc_type: locate source PDF under Data_PDF to derive folders.
    # (match by stem; rglob would treat the filename's [..] as a glob class)
    data_root = Path("/Users/jhyeong/Project/InsightLab/Data_PDF")
    src = next((p for p in data_root.rglob("*.pdf") if p.stem == stem), None)
    category = src.parent.parent.name if src else ""
    doc_type = src.parent.name if src else ""

    chunks = chunk_md_file(md_file, category=category, doc_type=doc_type)
    out = write_chunks(chunks, settings.chunks_dir / f"{stem}.jsonl")
    print(f"product={chunks[0].product_name!r} category={category} doc_type={doc_type}")
    print(f"{len(chunks)} chunks -> {out}")
    for c in chunks[:4]:
        print("-" * 70)
        print(f"[{c.chunk_index}] page={c.page} section={c.section!r} kind={c.kind}")
        print(c.text[:300])
