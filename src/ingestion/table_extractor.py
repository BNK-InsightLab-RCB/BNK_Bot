"""Coordinate-based table extraction for born-digital PDFs.

Korean financial product PDFs (BNK 약관/설명서) wrap most content in ruled
boxes. Docling's vision-based TableFormer fails to segment these line-bordered,
merged-cell tables: it drops whole sub-tables and scrambles row/column mapping
(e.g. period <-> interest-rate), which is unacceptable for financial RAG.

Since these PDFs are born-digital (real text layer) AND have vector ruling
lines, we reconstruct tables deterministically with pdfplumber's `lines`
strategy, which reads cell boundaries straight from the rulings. This preserves
label<->value pairing and merged-cell alignment with no OCR error.

This module produces, per page, an ordered list of Markdown blocks (free text
outside tables + reconstructed tables), so a faithful Markdown rendering of the
whole page can be assembled in reading order.
"""
from __future__ import annotations

from dataclasses import dataclass

import pdfplumber

# Use the vector ruling lines to define cells. Small tolerances absorb the
# sub-pixel gaps common in these exported PDFs.
TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 4,
    "join_tolerance": 4,
    "intersection_tolerance": 4,
}


@dataclass
class Block:
    """A positioned piece of page content rendered to Markdown."""

    top: float  # y of the block top, for reading-order sorting
    kind: str   # "text" | "table"
    md: str


def _esc(cell: str | None) -> str:
    """Normalise a cell value and escape Markdown table delimiters."""
    if not cell:
        return ""
    return " ".join(cell.split()).replace("|", r"\|")


def _merge_exclusive_columns(grid: list[list[str]]) -> list[list[str]]:
    """Collapse phantom column splits.

    Nested sub-table rulings add vertical lines that split the whole master
    grid into more columns than it logically has (e.g. an always-empty middle
    column). We merge two adjacent columns only when no single row populates
    both of them — i.e. they never carry conflicting data — so genuine
    multi-column data (period vs. rate, 고정금리 vs. 변동금리) is preserved.
    """
    if not grid:
        return grid
    while len(grid[0]) > 1:
        ncol = len(grid[0])
        merge_at = None
        for c in range(ncol - 1):
            co_occurs = any(row[c] and row[c + 1] for row in grid)
            if not co_occurs:
                merge_at = c
                break
        if merge_at is None:
            break
        for row in grid:
            a, b = row[merge_at], row[merge_at + 1]
            row[merge_at] = (a + " " + b).strip() if a and b else (a or b)
            del row[merge_at + 1]
    return grid


def clean_grid(rows: list[list[str | None]]) -> list[list[str]]:
    """Normalise a raw pdfplumber grid.

    - Drop fully-empty columns (rulings often create phantom columns).
    - For 2-column label|value tables only, merge wrapped continuation rows
      (a row whose label cell is empty is a line-wrap of the previous value).
      Wider data grids are left untouched so merged-cell alignment such as
      period<->rate is preserved verbatim.
    """
    if not rows:
        return []
    ncol = max(len(r) for r in rows)
    norm = [[_esc(r[c]) if c < len(r) else "" for c in range(ncol)] for r in rows]
    keep = [c for c in range(ncol) if any(r[c] for r in norm)]
    if not keep:
        return []
    grid = [[r[c] for c in keep] for r in norm]
    grid = _merge_exclusive_columns(grid)

    if not grid or len(grid[0]) != 2:
        return grid

    merged: list[list[str]] = [grid[0]]
    for row in grid[1:]:
        if not row[0]:  # empty label -> continuation of previous value cell
            prev = merged[-1]
            for i, val in enumerate(row):
                if val:
                    prev[i] = (prev[i] + " " + val).strip()
        else:
            merged.append(row)
    return merged


def grid_to_md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "|" + "|".join(["---"] * ncol) + "|",
    ]
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _word_in_any_bbox(word: dict, bboxes: list[tuple], tol: float = 2.0) -> bool:
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    for b in bboxes:
        if b[0] - tol <= cx <= b[2] + tol and b[1] - tol <= cy <= b[3] + tol:
            return True
    return False


def _text_blocks_outside(page: "pdfplumber.page.Page", bboxes: list[tuple]) -> list[Block]:
    """Group words that fall outside every table into per-line text blocks."""
    words = [w for w in page.extract_words() if not _word_in_any_bbox(w, bboxes)]
    if not words:
        return []
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    blocks: list[Block] = []
    cur_top = None
    cur: list[str] = []
    for w in words:
        if cur_top is None or abs(w["top"] - cur_top) <= 3:
            cur.append(w["text"])
            cur_top = w["top"] if cur_top is None else cur_top
        else:
            blocks.append(Block(cur_top, "text", " ".join(cur)))
            cur = [w["text"]]
            cur_top = w["top"]
    if cur:
        blocks.append(Block(cur_top, "text", " ".join(cur)))
    return blocks


def _bbox_inside(inner: tuple, outer: tuple, tol: float = 2.0) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and
            inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _top_level_tables(tables: list) -> list:
    """Keep only outermost tables.

    pdfplumber detects both a wrapping "master" table and the sub-tables nested
    inside its cells, which would render every nested block twice. The master
    grid already contains the nested content, so we drop any table whose bbox is
    fully inside a strictly larger one.
    """
    def area(t):
        b = t.bbox
        return abs((b[2] - b[0]) * (b[3] - b[1]))

    ordered = sorted(tables, key=area, reverse=True)
    kept: list = []
    for t in ordered:
        if any(_bbox_inside(t.bbox, k.bbox) and area(t) < area(k) for k in kept):
            continue
        kept.append(t)
    return kept


def extract_page_blocks(page: "pdfplumber.page.Page") -> list[Block]:
    """Return all content of a page as Markdown blocks in reading order."""
    tables = _top_level_tables(page.find_tables(TABLE_SETTINGS))
    bboxes = [t.bbox for t in tables]
    blocks: list[Block] = []
    for t in tables:
        rows = clean_grid(t.extract())
        if rows:
            blocks.append(Block(t.bbox[1], "table", grid_to_md(rows)))
    blocks.extend(_text_blocks_outside(page, bboxes))
    blocks.sort(key=lambda b: b.top)
    return blocks


def extract_markdown(pdf_path: str) -> str:
    """Full-document Markdown for a born-digital, ruled-table PDF."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            parts.append(f"<!-- page {i + 1} -->")
            for b in extract_page_blocks(page):
                parts.append(b.md)
    return "\n\n".join(parts) + "\n"
