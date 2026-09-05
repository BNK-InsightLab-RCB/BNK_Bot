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

# Docling 경로(스캔 PDF 폴백 · docx)가 내보내는 '내용 없는 placeholder'.
# 그대로 두면 텍스트 청크에 노이즈로 섞여 임베딩 품질을 떨어뜨린다.
#
# 광범위한 정규식(`<!--.*-->`)이 아니라 **정확 일치 허용목록**만 지운다: 금융 문서에서
# 정규식으로 쓸어내다 실제 데이터를 날리는 쪽이 노이즈보다 훨씬 위험하기 때문.
# 새 placeholder 를 발견하면 여기에 '정확한 문자열로' 추가할 것.
_PLACEHOLDER_LINES = frozenset({
    "<!-- image -->",
    "<!-- missing-text -->",
})


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

    for line in md.splitlines():
        s = line.strip()
        m = _PAGE_RE.match(s)
        if m:
            flush()
            page = int(m.group(1))
            continue
        if s in _PLACEHOLDER_LINES:
            # 내용이 없으므로 버린다. 단락 경계로는 쓰지 않는다(주변 빈 줄이 이미 경계).
            continue
        if s == "":
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
        s = re.sub(r"\[[^\]]*\]", "", source_stem)          # drop [부산은행]/[신탁계약서] etc.
        # 선두 문서번호가 괄호 그룹 바로 앞에 오는 형태: "2605(부산은행)부산은행 …"
        s = re.sub(r"^\s*\d{3,}\s*(?=\()", "", s)
        # 선두 목록번호 제거: "14.", "6._", 그리고 펀드 신탁계약서의 "9-다.", "1-다."
        # (하위 항목 표기 `-가/-나/-다`까지 함께 벗긴다.)
        # 뒤의 (?=\D) 가 "3.6%정기예금" 같은 소수점 상품명을 보호한다 —
        # 구분자 다음 글자가 숫자면 목록번호가 아니라 상품명의 일부다.
        s = re.sub(r"^\s*\d+(?:\s*-\s*[가-힣])?\s*[._]\s*(?=\D)", "", s)
        for w in self._DOC_TYPE_WORDS:                       # cut at doc-type word
            if w in s:
                s = s.split(w)[0]
                break
        s = re.sub(r"\([^)]*\)", "", s)                      # drop (date)/(ver)
        s = re.sub(r"[_\s]+", " ", s).strip(" _-")
        s = re.sub(r"\s*\d{4,6}\s*심의\s*$", "", s).strip()  # drop trailing "YYYYMM 심의"
        if s:
            return s
        # 문서종류 앞이 비는 형태 — "(적립식)상품설명서(OnlyOne주거래우대적금)" 처럼
        # 상품명이 **뒤쪽 괄호 안에** 있는 경우. 원본에서 가장 긴 괄호 그룹을 쓴다
        # (날짜·버전 괄호보다 상품명이 길다는 경험칙; 없으면 원본 그대로).
        groups = [g for g in re.findall(r"\(([^)]*)\)", source_stem) if not re.fullmatch(r"[\d.\s_-]*", g)]
        if groups:
            return max(groups, key=len).strip()
        return source_stem

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


# 임베딩 모델(KURE-v1)의 입력 상한 8,192 토큰에 대응하는 문자 수. 실측으로 한국어는
# 약 1.8자/토큰이라 8,192토큰 ≈ 14,700자다. 여유를 두고 12,000자로 잡는다.
MAX_EMBED_CHARS = 12_000


def cap_for_embedding(body: str, kind: str, limit: int = MAX_EMBED_CHARS) -> list[str]:
    """임베딩 상한을 넘는 덩어리를 나눈다. 넘지 않으면 그대로 1개 반환.

    **왜 표까지 쪼개는가.** "표는 통째로 유지"가 원칙이지만, 상한을 넘으면 모델이
    앞부분만 읽고 **초과분을 조용히 버린다** — 통째로 뒀는데 정작 뒷부분이 검색되지
    않으므로 원칙이 이미 깨진 상태다. 쪼개면 전부 색인된다.
    실측: 전체 237,911청크 중 초과는 114개(0.05%), 영향 문서는 11개(0.3%)뿐이라
    대다수 문서의 청킹 결과는 이 규칙과 무관하게 동일하다.
    (부수 효과: 초과 청크가 57개였던 보험 약관에서 어텐션 메모리가 폭증해 적재가
     2시간 넘게 정지했다 — 상한이 그 정지도 없앤다.)

    표는 **행 경계**에서만 자른다(행 중간을 자르면 라벨↔값이 깨진다).
    헤더 행을 반복하지 않는 이유: 글자를 새로 만들지 않기 위해서다 —
    `check_chunk_conservation` 이 "원본 글자 = 청크 글자"를 검증하는데, 헤더를
    복제하면 그 불변식이 깨져 진짜 손실과 구분할 수 없게 된다.
    """
    if len(body) <= limit:
        return [body]
    lines = body.split("\n")
    out, cur = [], []
    for line in lines:
        # 이 줄을 넣으면 상한을 넘고, 이미 담긴 게 있으면 끊는다(줄 = 표의 행 경계).
        if cur and sum(len(x) + 1 for x in cur) + len(line) > limit:
            out.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


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
def _context_header(label: str, category: str, doc_type: str, section: str) -> str:
    """청크 앞에 붙는 컨텍스트 한 줄. **이 줄까지 포함해서 임베딩된다.**

    ``label`` 에는 **가공하지 않은 파일명(stem)** 을 쓴다. 예전엔 파일명에서 상품명을
    잘라낸 값을 넣었는데, 그 추출은 파일명 형태에 따라 성공/실패가 갈려
    (`약관_신한지수연계…`, `개정후주택청약종합저축`) **원본에 없는 오류를 만들어냈다**.

    측정 근거(`scripts/ab_context_header.py`, 예금 163건·15문항):
      A 정제된 상품명 pass@1 14/15 · pass@5 15/15
      B 파일명 그대로 pass@1 13/15 · pass@5 15/15   ← 채택
      C 헤더 없음     pass@1 10/15 · pass@5 13/15
    → **헤더 자체는 반드시 필요**(C 가 확연히 나쁨)하지만, **정제의 이득은 입증되지 않았다**
      (A·B 는 pass@5 동일, pass@1 1문항 차이인데 그마저 같은 문서 내 청크 순서 차이).
      게다가 질문셋이 상품명을 명시한 문항 위주라 A 에 유리한 조건이었다.
    → 이득이 측정되지 않는 가공은 넣지 않는다. 실패할 수 없는 쪽을 고른다.
    """
    head = f"[{label}]"
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
    # macOS 파일명은 NFD 라 반드시 정규화한다 — 헤더는 임베딩에 들어가므로
    # 정규화를 빠뜨리면 겉보기 같은 한글이 다른 토큰으로 인코딩된다.
    stem = _nfc(stem)
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
        # 임베딩 한계를 넘는 덩어리는 여기서 쪼갠다. 표도 예외가 아니다 — 이유는
        # `cap_for_embedding` 참조(통째로 두면 뒷부분이 조용히 버려진다).
        for piece in cap_for_embedding(body, kind):
            _emit_one(piece, page, kind)

    def _emit_one(body: str, page: int, kind: str) -> None:
        # 헤더에는 가공 없는 파일명(stem)을, payload 라벨에는 추출된 상품명을 쓴다.
        # 둘을 분리한 이유: 헤더는 **검색 벡터에 들어가므로** 추출 실패가 검색 품질을
        # 오염시킨다. payload 는 표시·필터용이라 틀려도 검색엔 영향이 없다.
        # (payload product_name 을 어떻게 할지는 미결정 — CLAUDE.md "자료 가공 원칙" 참조)
        header = _context_header(stem, category, doc_type, section)
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
