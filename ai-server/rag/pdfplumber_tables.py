from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pdfplumber


TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "intersection_tolerance": 5,
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 8,
}


@dataclass(frozen=True)
class ExtractedTable:
    page_number: int
    table_index: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]

    @property
    def area(self) -> float:
        x0, y0, x1, y1 = self.bbox
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)

    @property
    def text(self) -> str:
        return _table_text(self.rows)


def extract_pdfplumber_tables(pdf_path: Path) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table_index, table in enumerate(page.find_tables(table_settings=TABLE_SETTINGS), start=1):
                rows = normalize_rows(table.extract())
                if not _has_useful_text(rows):
                    continue
                tables.append(
                    ExtractedTable(
                        page_number=page.page_number,
                        table_index=table_index,
                        bbox=tuple(float(value) for value in table.bbox),
                        rows=clean_table_rows(rows),
                    )
                )
    return deduplicate_nested_tables(tables)


def render_pdfplumber_tables_markdown(pdf_path: Path) -> str:
    tables = extract_pdfplumber_tables(pdf_path)
    if not tables:
        return ""

    parts = ["## 표 추출 보강"]
    for table in tables:
        rendered = render_table_markdown(table.rows)
        if not rendered:
            continue
        heading = _table_heading(table)
        parts.extend(
            [
                "",
                f"### {heading}",
                "",
                f"<!-- page: {table.page_number}, extractor: pdfplumber, table_id: p{table.page_number}_t{table.table_index} -->",
                "",
                rendered,
            ]
        )
    return "\n".join(parts).strip()


def deduplicate_nested_tables(tables: Iterable[ExtractedTable]) -> list[ExtractedTable]:
    kept: list[ExtractedTable] = []
    for table in sorted(tables, key=lambda item: (item.page_number, -item.area)):
        if any(_is_nested_duplicate(table, parent) for parent in kept if parent.page_number == table.page_number):
            continue
        kept.append(table)
    return sorted(kept, key=lambda item: (item.page_number, item.bbox[1], item.bbox[0]))


def clean_table_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned = remove_empty_rows(rows)
    cleaned = merge_mutually_exclusive_columns(cleaned)
    cleaned = merge_continuation_rows(cleaned)
    cleaned = remove_empty_rows(cleaned)
    return cleaned


def normalize_rows(rows: list[list[object | None]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    normalized = []
    for row in rows:
        normalized.append([normalize_cell(row[index] if index < len(row) else "") for index in range(width)])
    return normalized


def normalize_cell(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _normalize_known_cell_terms(text.strip())
    return text


def remove_empty_rows(rows: list[list[str]]) -> list[list[str]]:
    without_empty_rows = [row for row in rows if any(cell.strip() for cell in row)]
    return remove_empty_columns(without_empty_rows)


def remove_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    keep_indexes = [
        index
        for index in range(width)
        if any(row[index].strip() for row in padded)
    ]
    return [[row[index] for index in keep_indexes] for row in padded]


def merge_mutually_exclusive_columns(rows: list[list[str]]) -> list[list[str]]:
    current = remove_empty_columns(rows)
    changed = True
    while changed and current:
        changed = False
        width = len(current[0])
        for index in range(width - 1):
            if _should_merge_columns(current, index, index + 1):
                current = [_merge_columns_in_row(row, index, index + 1) for row in current]
                current = remove_empty_columns(current)
                changed = True
                break
    return current


def merge_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    width = len(rows[0])
    if width not in {2, 3}:
        return rows

    merged: list[list[str]] = []
    for row in rows:
        first = row[0].strip()
        rest = [cell.strip() for cell in row[1:]]
        if merged and not first and any(rest):
            target = merged[-1]
            for index, cell in enumerate(rest, start=1):
                if not cell:
                    continue
                target[index] = _join_cell_text(target[index], cell)
            continue
        merged.append(row[:])
    return merged


def render_table_markdown(rows: list[list[str]]) -> str:
    rows = remove_empty_rows(rows)
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    if _looks_like_header(padded[0]):
        header = padded[0]
        body = padded[1:]
    else:
        header = _default_header(width)
        body = padded

    lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _should_merge_columns(rows: list[list[str]], left: int, right: int) -> bool:
    left_count = 0
    right_count = 0
    both_count = 0
    for row in rows:
        has_left = bool(row[left].strip())
        has_right = bool(row[right].strip())
        left_count += int(has_left)
        right_count += int(has_right)
        both_count += int(has_left and has_right)

    if left_count == 0 or right_count == 0:
        return True
    if both_count > 0:
        return False
    if min(left_count, right_count) > 2:
        return False
    if left_count + right_count < 2:
        return False
    return True


def _merge_columns_in_row(row: list[str], left: int, right: int) -> list[str]:
    merged = row[:]
    merged[left] = _join_cell_text(merged[left], merged[right])
    del merged[right]
    return merged


def _join_cell_text(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if _is_korean_syllable_fragment(left, right):
        return f"{left}{right}"
    return f"{left}\n{right}"


def _is_korean_syllable_fragment(left: str, right: str) -> bool:
    return bool(re.fullmatch(r"[가-힣]", left) and re.fullmatch(r"[가-힣]", right))


def _looks_like_header(row: list[str]) -> bool:
    filled = [cell for cell in row if cell.strip()]
    if len(filled) < 2:
        return False
    header_terms = {"구분", "구 분", "내용", "내 용", "항목", "용어", "이율", "가입기간", "기본이율"}
    return any(cell.strip() in header_terms for cell in filled)


def _default_header(width: int) -> list[str]:
    if width == 2:
        return ["항목", "내용"]
    if width == 3:
        return ["항목", "구분", "내용"]
    return [f"열{index}" for index in range(1, width + 1)]


def _escape_markdown_cell(cell: str) -> str:
    return re.sub(r"\s*\n\s*", "<br>", cell.strip()).replace("|", "\\|")


def _has_useful_text(rows: list[list[str]]) -> bool:
    return len(_table_text(rows)) >= 8


def _is_nested_duplicate(candidate: ExtractedTable, parent: ExtractedTable) -> bool:
    if candidate.area >= parent.area:
        return False
    if _bbox_containment(candidate.bbox, parent.bbox) < 0.95:
        return False
    candidate_text = candidate.text
    parent_text = parent.text
    if not candidate_text or not parent_text:
        return False
    return _text_containment(candidate_text, parent_text) >= 0.75


def _bbox_containment(child: tuple[float, float, float, float], parent: tuple[float, float, float, float]) -> float:
    cx0, cy0, cx1, cy1 = child
    px0, py0, px1, py1 = parent
    intersection_width = max(0.0, min(cx1, px1) - max(cx0, px0))
    intersection_height = max(0.0, min(cy1, py1) - max(cy0, py0))
    child_area = max(0.0, cx1 - cx0) * max(0.0, cy1 - cy0)
    if child_area == 0:
        return 0.0
    return (intersection_width * intersection_height) / child_area


def _text_containment(child_text: str, parent_text: str) -> float:
    child_tokens = _tokenize_for_overlap(child_text)
    parent_tokens = _tokenize_for_overlap(parent_text)
    if not child_tokens:
        return 0.0
    overlap = sum(1 for token in child_tokens if token in parent_tokens)
    return overlap / len(child_tokens)


def _tokenize_for_overlap(text: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z가-힣%/().]+", unicodedata.normalize("NFC", text))


def _table_text(rows: list[list[str]]) -> str:
    return " ".join(cell.strip() for row in rows for cell in row if cell.strip())


def _table_heading(table: ExtractedTable) -> str:
    label = ""
    for row in table.rows:
        for cell in row:
            normalized = re.sub(r"\s+", " ", cell).strip()
            if normalized:
                label = normalized
                break
        if label:
            break
    if len(label) > 28:
        label = label[:28].rstrip()
    base = f"page {table.page_number} table {table.table_index}"
    return f"{base} {label}" if label else base


def _normalize_known_cell_terms(text: str) -> str:
    replacements = {
        "가 능": "가능",
        "불 가": "불가",
        "해 당": "해당",
        "구 분": "구분",
        "내 용": "내용",
        "용 어": "용어",
        "특 징": "특징",
        "장 점": "장점",
        "단 점": "단점",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    return text
